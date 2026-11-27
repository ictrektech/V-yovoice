package vos

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"yovoice/internal/msg"
	"yovoice/internal/schema"
	"yovoice/internal/store"
	"yovoice/internal/workbench"
)

const nodeBundleLimit = 500 << 20

type nodeBundle struct {
	Method string          `json:"method"`
	Data   json.RawMessage `json:"data"`
	ID     string          `json:"id"`
	State  schema.State    `json:"state"`
}

func nodeSnapshot(job Job, state schema.State) nodeBundle {
	ids := map[string]bool{}
	var visit func(any)
	visit = func(value any) {
		switch x := value.(type) {
		case string:
			if schema.ValidID(x) {
				ids[x] = true
			}
		case []any:
			for _, item := range x {
				visit(item)
			}
		case map[string]any:
			for _, item := range x {
				visit(item)
			}
		}
	}
	collect := func(value any) {
		encoded, _ := json.Marshal(value)
		var row any
		if json.Unmarshal(encoded, &row) == nil {
			visit(row)
		}
	}
	collect(job.Data)
	clean := schema.State{}
	// 递归收集任务快照实际引用的作品、历史、角色和音色，忽略用户配置和其他作品。
	selected := map[string]bool{}
	for {
		count := len(selected)
		for _, row := range state.Drafts {
			if ids[row.ID] && !selected[row.ID] {
				selected[row.ID] = true
				clean.Drafts = append(clean.Drafts, row)
				collect(row)
			}
		}
		for _, row := range state.History {
			if ids[row.ID] && !selected[row.ID] {
				selected[row.ID] = true
				clean.History = append(clean.History, row)
				collect(row)
			}
		}
		for _, row := range state.Characters {
			if ids[row.ID] && !selected[row.ID] {
				selected[row.ID] = true
				row.Preview = nil
				clean.Characters = append(clean.Characters, row)
				collect(row)
			}
		}
		for _, row := range state.Voices {
			if ids[row.ID] && !selected[row.ID] {
				selected[row.ID] = true
				clean.Voices = append(clean.Voices, row)
			}
		}
		if len(selected) == count {
			break
		}
	}
	return nodeBundle{job.Method, job.Data, job.ID, clean}
}

func nodeMedia(state schema.State) map[string]bool {
	files := map[string]bool{}
	add := func(kind, name string) {
		if name != "" {
			files[kind+"/"+name] = true
		}
	}
	for _, row := range state.Voices {
		add("voices", row.FileName)
	}
	for _, name := range stateFiles(state) {
		add("outputs", name)
	}
	for _, row := range state.Drafts {
		if row.Timeline != nil {
			for _, media := range row.Timeline.Assets {
				add("outputs", media.FileName)
			}
		}
	}
	return files
}

func writeNodeBundle(path string, bundle nodeBundle, files map[string]bool, source *store.Store) error {
	return withNodeFile(path, func(out *os.File) error {
		zipOut := zip.NewWriter(out)
		metadata, err := json.Marshal(bundle)
		if err != nil || len(metadata) > 32<<20 {
			return fmt.Errorf("invalid workbench bundle metadata")
		}
		entry, err := zipOut.Create("job.json")
		if err != nil {
			return err
		}
		if _, err = entry.Write(metadata); err != nil {
			return err
		}
		remaining := int64(nodeBundleLimit - len(metadata))
		for name := range files {
			kind, file, _ := strings.Cut(name, "/")
			located, err := source.MediaPath(kind, file)
			if err != nil {
				return err
			}
			in, err := os.Open(located)
			if err != nil {
				return err
			}
			entry, err = zipOut.CreateHeader(&zip.FileHeader{Name: name, Method: zip.Store})
			if err == nil {
				var n int64
				n, err = io.Copy(entry, io.LimitReader(in, remaining+1))
				remaining -= n
			}
			in.Close()
			if err != nil {
				return err
			}
			if remaining < 0 {
				return fmt.Errorf("workbench bundle too large")
			}
		}
		return zipOut.Close()
	})
}

func withNodeFile(path string, write func(*os.File) error) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	out, err := os.CreateTemp(filepath.Dir(path), ".node-job-")
	if err != nil {
		return err
	}
	defer os.Remove(out.Name())
	defer out.Close()
	if err = write(out); err != nil {
		return err
	}
	if err = out.Sync(); err != nil {
		return err
	}
	if err = out.Close(); err != nil {
		return err
	}
	return os.Rename(out.Name(), path)
}

func unpackNodeBundle(path, mediaRoot string) (nodeBundle, map[string]bool, error) {
	var bundle nodeBundle
	seen := map[string]bool{}
	archive, err := zip.OpenReader(path)
	if err != nil {
		return bundle, nil, err
	}
	defer archive.Close()
	if len(archive.File) > 4096 {
		return bundle, nil, fmt.Errorf("too many workbench bundle files")
	}
	target := &store.Store{Root: mediaRoot}
	remaining := uint64(nodeBundleLimit)
	for _, entry := range archive.File {
		if seen[entry.Name] || entry.UncompressedSize64 > remaining || !entry.Mode().IsRegular() {
			return bundle, nil, fmt.Errorf("invalid workbench bundle entry")
		}
		remaining -= entry.UncompressedSize64
		seen[entry.Name] = true
		stream, err := entry.Open()
		if err != nil {
			return bundle, nil, err
		}
		if entry.Name == "job.json" {
			const maxMetadata = 32 << 20
			if entry.UncompressedSize64 > maxMetadata {
				stream.Close()
				return bundle, nil, fmt.Errorf("workbench metadata too large")
			}
			raw, readErr := io.ReadAll(io.LimitReader(stream, maxMetadata+1))
			err = readErr
			if err == nil {
				err = json.Unmarshal(raw, &bundle)
			}
		} else {
			kind, file, _ := strings.Cut(entry.Name, "/")
			destination, pathErr := target.MediaPath(kind, file)
			err = pathErr
			if err == nil {
				err = withNodeFile(destination, func(out *os.File) error {
					n, e := io.Copy(out, io.LimitReader(stream, int64(entry.UncompressedSize64)+1))
					if e == nil && uint64(n) != entry.UncompressedSize64 {
						e = fmt.Errorf("incomplete workbench bundle")
					}
					return e
				})
			}
		}
		stream.Close()
		if err != nil {
			return bundle, nil, err
		}
	}
	if !seen["job.json"] || !schema.ValidID(bundle.ID) || !nodeMethod(bundle.Method) {
		return bundle, nil, fmt.Errorf("invalid workbench job")
	}
	delete(seen, "job.json")
	return bundle, seen, nil
}

func readNodeMetadata(path string) (nodeBundle, error) {
	var result nodeBundle
	z, err := zip.OpenReader(path)
	if err != nil {
		return result, err
	}
	defer z.Close()
	file, err := z.Open("job.json")
	if err != nil {
		return result, err
	}
	defer file.Close()
	err = json.NewDecoder(io.LimitReader(file, 32<<20)).Decode(&result)
	return result, err
}

func nodeMediaDigest(path string) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, nodeBundleLimit+1))
	if err == nil && n > nodeBundleLimit {
		err = fmt.Errorf("workbench media exceeds limit")
	}
	return h.Sum(nil), err
}

func nodeMethod(method string) bool {
	switch method {
	case "generation.start", "generation.cue", "generation.alignLyrics", "character.preview", "melody.plan", "melody.cover", "melody.listen":
		return true
	}
	return false
}

// RunNodeJob 在独立目录重用主实例的执行逻辑。
func RunNodeJob(ctx context.Context, root, input, output, runtime string) error {
	initial, _, err := unpackNodeBundle(input, root)
	if err != nil {
		return err
	}
	w, err := workbench.New(root)
	if err != nil {
		return err
	}
	defer w.Close()
	if err = w.UseBundled(runtime); err != nil {
		return err
	}
	if err = w.Store.Update(func(s *schema.State) {
		s.Drafts, s.History, s.Characters, s.Voices = initial.State.Drafts, initial.State.History, initial.State.Characters, initial.State.Voices
	}, true); err != nil {
		return err
	}
	if err = w.SyncSharedModels(); err != nil {
		return err
	}
	job := Job{ID: initial.ID, Method: initial.Method, Data: initial.Data}
	if err = startSnapshot(ctx, w, job); err != nil {
		return err
	}
	select {
	case <-w.Done():
	case <-ctx.Done():
		w.UnloadRuntime()
		return ctx.Err()
	}
	w.UnloadRuntime()
	after := w.Store.Read()
	if job.Method != "melody.listen" && (after.Activity == nil || after.Activity.Status != "completed") {
		if after.Activity != nil && after.Activity.ErrorCode != nil {
			return fmt.Errorf("workbench operation failed: %s", *after.Activity.ErrorCode)
		}
		return fmt.Errorf("workbench operation did not complete")
	}
	after = schema.State{Activity: after.Activity, History: after.History, Drafts: after.Drafts, Previews: after.Previews, Melody: after.Melody}
	files := nodeMedia(after)
	for name := range nodeMedia(initial.State) {
		delete(files, name)
	}
	return writeNodeBundle(output, nodeBundle{Method: job.Method, ID: job.ID, State: after}, files, w.Store)
}

func applyNodeResult(w *workbench.Workbench, job Job, initial, output nodeBundle, files map[string]bool, stage string) error {
	if output.ID != job.ID || output.Method != job.Method {
		return fmt.Errorf("workbench job receipt mismatch")
	}
	expected := nodeMedia(output.State)
	for name := range nodeMedia(initial.State) {
		delete(expected, name)
	}
	if !reflect.DeepEqual(expected, files) {
		return fmt.Errorf("workbench output manifest mismatch")
	}
	for name := range files {
		kind, file, _ := strings.Cut(name, "/")
		if kind != "outputs" {
			return fmt.Errorf("invalid workbench output type")
		}
		destination, err := w.Store.MediaPath(kind, file)
		if err != nil {
			return err
		}
		source := filepath.Join(stage, kind, file)
		if err = os.Link(source, destination); err != nil {
			if !os.IsExist(err) {
				return err
			}
			before, e := nodeMediaDigest(source)
			current, o := nodeMediaDigest(destination)
			// 重试只能复用之前已经核验并发布的同一内容。
			if e != nil || o != nil || !slices.Equal(before, current) {
				return fmt.Errorf("workbench output name collision")
			}
		}
	}
	return w.Store.Update(func(s *schema.State) {
		for _, row := range output.State.History {
			at := slices.IndexFunc(s.History, func(current schema.Generation) bool { return row.ID == current.ID })
			before := slices.IndexFunc(initial.State.History, func(current schema.Generation) bool { return row.ID == current.ID })
			if at < 0 && before < 0 {
				s.History = append([]schema.Generation{row}, s.History...)
			}
			if job.Method == "generation.alignLyrics" && at >= 0 && before >= 0 &&
				reflect.DeepEqual(s.History[at].LyricTimes, initial.State.History[before].LyricTimes) &&
				reflect.DeepEqual(s.History[at].LyricWords, initial.State.History[before].LyricWords) {
				s.History[at].LyricTimes, s.History[at].LyricWords = row.LyricTimes, row.LyricWords
			}
		}
		for _, row := range output.State.Drafts {
			if job.Method != "generation.start" && job.Method != "generation.cue" {
				break
			}
			at := slices.IndexFunc(s.Drafts, func(current schema.Draft) bool { return row.ID == current.ID })
			before := slices.IndexFunc(initial.State.Drafts, func(current schema.Draft) bool { return row.ID == current.ID })
			if at >= 0 && before >= 0 && reflect.DeepEqual(s.Drafts[at].Timeline, initial.State.Drafts[before].Timeline) {
				s.Drafts[at].Timeline = row.Timeline
			}
		}
		for _, row := range output.State.Previews {
			if !slices.ContainsFunc(s.Previews, func(current schema.CharacterPreview) bool { return row.FileName == current.FileName }) {
				s.Previews = append(s.Previews, row)
			}
		}
		if output.State.Melody != nil {
			s.Melody = output.State.Melody
		}
		activity := output.State.Activity
		if activity == nil {
			activity = &schema.Activity{Kind: "generate", Code: msg.ActivityGenerate, Status: "completed", StartedAt: job.Created}
		}
		activity.SelectedNode = job.Node.NodeID
		activity.ActualNode = job.Node.NodeID
		activity.RequestID = job.ID
		s.Activity = activity
	}, true)
}
