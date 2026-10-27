package store

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"
	"yovoice/internal/schema"
)

// 状态库升级：PRAGMA user_version 记录已执行的步骤数，打开时按顺序补跑缺少的步骤，全部在同一事务内完成，
// 失败时整体回滚、版本不变。已有数据的库升级前先留一份完整副本。
// 已发布的步骤不能修改，表结构或已保存数据的格式变化时在末尾追加新步骤；旧格式只在这里转换，读取代码只认当前格式。

// migration 是一次升级：sql 修改表结构，data 改写已保存的记录，二者按需填写；root 为数据目录。
type migration struct {
	sql  string
	data func(tx *sql.Tx, root string) error
}

var migrations = []migration{
	// 1：建表。
	{sql: `CREATE TABLE settings (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE characters (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE drafts (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE voices (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE models (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE history (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE ai_providers (key TEXT PRIMARY KEY, pos INTEGER NOT NULL, data TEXT NOT NULL);
	 CREATE TABLE private (key TEXT PRIMARY KEY, data TEXT NOT NULL);`},
	// 2：补齐旧作品（台词 ID、空乐谱、旧故事的整篇音频放上时间线）；助手旧消息的工具卡片并入内容块；
	// 旧版下载的内核按安装目录名补记版本。
	{data: func(tx *sql.Tx, root string) error {
		if e := upgradeDrafts(tx); e != nil {
			return e
		}
		if e := rewriteRows(tx, "settings", assistantBlocks); e != nil {
			return e
		}
		return runtimeVersion(tx, root)
	}},
	// 3：按本次模型目录更新前的清单，为已安装模型补记主文件 SHA256。
	{data: func(tx *sql.Tx, root string) error {
		return rewriteRows(tx, "models", func(_ string, data []byte) ([]byte, error) {
			return backfillModelSHA256(data)
		})
	}},
}

// legacyModelSHA256 冻结本次目录更新前的主文件摘要，不能改成读取运行时目录，否则以后的目录更新会让旧记录冒充新版本。
var legacyModelSHA256 = map[string]string{
	"index-2.5-q8":                   "5e827b2072042e4a1b21ccf24a5cb4f71cb1011403067a0a9b039311d8b38628",
	"index-2.5-f16":                  "87bed9b82fc8f22119a1a1042332091016c28e37f29b0e93343ccdbfa76ef66a",
	"index-2.5-orig":                 "2c736df55a306155df4e607f49fe963cf2192fc2193ad449a4bdffb15e52b93a",
	"index-2-q8":                     "f9be73ac5b6cbdc5f603f04dcb6c9fe37b3a301a365a1ea8d580d3ef7ba22e8e",
	"index-2-f16":                    "0f7b95d3d32e18bf9352912a7b21a0bd4a8406853a0aaa2c9180f77389c21523",
	"index-2-orig":                   "c96cb948339b7169b7240f43dbd42ad6354ae3d0a22465e292ec8e090c338e16",
	"voxcpm2-q8":                     "c8e01ab4416011e12a28f24ede298a1aa5ce64b43f8e8aaad53b1e2fe7c96432",
	"voxcpm2-bf16":                   "0c0cd2515c7a1145c0ddba06c871724656c36cb53ee3b0118116b34cb4153699",
	"voxcpm2-orig":                   "13181e01e15d555c9eae7779626eb395c69334f15e948c9ea265ddf37ab50b16",
	"omnivoice-q8":                   "2f4be637278043c6842de5b85d681532030e9eb6ffe0f8b0e320f68238e3da8b",
	"omnivoice-bf16":                 "7301a41a0a5a2cb04430c1831a705e3906bfca51562c5cdb2f30a90d505a819c",
	"omnivoice-f16":                  "7421b6c387351d2cdce7eb8b931fa279739d628ef25acd4ff2062a70e6e1ab63",
	"qwen3-tts-base-q8":              "b55e06c7890d43c208d15aed8b4ed3f18215f295e47d5960e061b15bff338ab0",
	"qwen3-tts-base-bf16":            "f5cf4c37b969335e0ffb657119e52025e26192553119590d59fa17b8d36e8b29",
	"qwen3-tts-base-orig":            "7ab774d56ab9ed9ee7d0ae50917798cda23c7bcc11eaa6c3a4ae32068718b1c1",
	"qwen3-tts-customvoice-q8":       "3cfaac8e9f13554f6daea3c5e0c53fede71ef5500cbaae7445e5fc3a5bb12e72",
	"qwen3-tts-customvoice-bf16":     "ef55652c7aa919dc5eeb7967c782a17a6f5d9a8b775337376a4678d37e71a11c",
	"qwen3-tts-base-0.6b-q8":         "771420bd20ff5f35407b4fa9cf9c5461e153800d3d772ef51c9febc0a520855d",
	"qwen3-tts-base-0.6b-bf16":       "97d418048b07b5b267628da955b27db4c57b353ded8089de01a469b474255b8d",
	"qwen3-tts-voicedesign-q8":       "1bcef9a8c021072fca40e00498e00af9091fbe6d3ae4f87567cfee885d6c7554",
	"qwen3-tts-voicedesign-bf16":     "f4cebcd68023a2db7c3fc8d52d1d28eafb22d4e3b7a64e12c4f946a300536f86",
	"breeze-tts-2-q8":                "0de52d61560f9f6b2dfeca79f9100f8fce0c2b17c52ec30622e23e150df1ad88",
	"breeze-tts-2-q4":                "b1c2467ac542d9ba05ad0e7bd331b09137f3752f1be2d3c491bd1b2045df6767",
	"breeze-tts-2-bf16":              "a00c9f678b4c5ae03d1dcd228f636b329352cda200823faef4e01d3bd97c0a89",
	"kokoro-82m-q8":                  "5d800fd204029302c10313daeafdb31c875c7c29ae31974d0d156cc7f512d1d0",
	"kokoro-82m-bf16":                "51d10c63557d21f70ef5d607e91c11023cf408dbc3af24c283b18106778e1e67",
	"kokoro-1.1-zh-q8":               "44d58f231606d7cb9c17eee649ed195a680f356de368068d03a83d9f188ec9c7",
	"ace-step-1.5-turbo-bf16":        "93974239a29a1a821b3cc1b1ca7e1c6229b1a900a0e44a1a9770bb2271d2be5f",
	"ace-step-1.5-turbo-q8":          "cd7bf272588f548d4a253f57483132ef0f8f54a549f26471b09caa72c654270b",
	"ace-step-1.5-xl-turbo-bf16":     "9529c24b3b929c701b34d0eee3686c76084b99e993539802f95ed171e954ff65",
	"ace-step-1.5-xl-turbo-q8":       "60ddf6d4ebec685c89fb451af8a7983aca65c58baa6aa6e5e25d168b4b7613f8",
	"stable-audio-3-small-music-q8":  "89bb22db5fa68ab8f1d90af0a9f88121977c945bdb99a57c96b1e88fa34bf1c8",
	"stable-audio-3-small-music-f16": "66f36741c19f9ca08e7239f89253141fe08a1f88de92f4459385ad80fc1c0e23",
	"stable-audio-3-small-sfx-q8":    "5bb1ec653134e63dac46264e336ae198a2590195fc996fcd0605021215e9b26f",
	"stable-audio-3-small-sfx-f16":   "0d8948b947f137c163983f060973d80e9bb699ea11c303327cd7005402f93918",
	"stable-audio-3-medium-q8":       "262c8259cfeac055258d28bfc126bcafb5c776fac44165222b186270f99b07ca",
	"stable-audio-3-medium-f16":      "d701796858eb54347ade9e80240a58d4eccf1890a9ccff3ed3b0640be5273a23",
	"yue2-3b-q8":                     "52be345b5155bf9ef0b2411e7df8d1d2b8e13b6d977a2f70c35612ec69b1f591",
	"yue2-3b-bf16":                   "4cf3fdffbaaed2d8e30a3122ac7cd27d0c96f8921805f173da9758c685b3c7d6",
	"yue2-3b-q4":                     "b80215b59a7fe41a4c76b6163c0ae1031672f892b5951d66fefaa2053a815029",
	"sheetsage2-orig":                "d858bfdf5ac7be16261ac6ee38754d6fca502149131b44a5262b4039fb72876e",
	"lyric-align-q8":                 "75209490b11cec2b0db749ca5f4ff92266f58efd30f7fd04d9eb2a3ac9cc929f",
	"musescore-general-sf2":          "ee51d2c4b1525e70f19a45909c4fd7a2e26d91d115fa89dbf5a6bc413d8b9bf3",
	"generaluser-gs-sf2":             "9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe",
	"sgm-v2-sf2":                     "86f2dc4b6983257ce7f983e62afedd22ea35e6e53e3f391360d9f125ce1ea088",
}

func backfillModelSHA256(data []byte) ([]byte, error) {
	var model schema.InstalledModel
	if err := json.Unmarshal(data, &model); err != nil {
		return nil, err
	}
	if model.SHA256 != "" || legacyModelSHA256[model.ID] == "" {
		return nil, nil
	}
	model.SHA256 = legacyModelSHA256[model.ID]
	return json.Marshal(model)
}

func backfillModelSHA256State(state *schema.State) {
	for i := range state.Models {
		if state.Models[i].SHA256 == "" {
			state.Models[i].SHA256 = legacyModelSHA256[state.Models[i].ID]
		}
	}
}

// schemaVersion 是当前应用对应的状态库版本。
var schemaVersion = len(migrations)

// upgradeSnapshot 是升级前副本的文件名前缀，最多保留 keepCorrupt 份。
const upgradeSnapshot = "yovoice.upgrade"

func migrate(db *sql.DB, root string) error {
	var version int
	if e := db.QueryRow("PRAGMA user_version").Scan(&version); e != nil {
		return e
	}
	if version > schemaVersion {
		return fmt.Errorf("数据库版本 %d 高于当前应用支持的版本 %d，请升级应用", version, schemaVersion)
	}
	if version == schemaVersion {
		return nil
	}
	if version > 0 {
		// 升级会改写已保存的数据，先留一份副本，升级逻辑有误时仍能找回原始数据。
		path := filepath.Join(root, fmt.Sprintf("%s-v%d-%s.db", upgradeSnapshot, version, time.Now().Format("20060102-150405.000000000")))
		if e := backup(db, path); e != nil {
			return e
		}
		pruneSnapshots(root, upgradeSnapshot+"-*.db", keepCorrupt)
	}
	tx, e := db.Begin()
	if e != nil {
		return e
	}
	defer tx.Rollback()
	for _, step := range migrations[version:] {
		if step.sql != "" {
			if _, e = tx.Exec(step.sql); e != nil {
				return e
			}
		}
		if step.data != nil {
			if e = step.data(tx, root); e != nil {
				return e
			}
		}
	}
	if _, e = tx.Exec(fmt.Sprintf("PRAGMA user_version = %d", schemaVersion)); e != nil {
		return e
	}
	return tx.Commit()
}

// rewriteRows 逐行交给 change 改写，change 返回 nil 表示该行不变；只写回变化的行。
func rewriteRows(tx *sql.Tx, table string, change func(key string, data []byte) ([]byte, error)) error {
	rows, e := tx.Query("SELECT key, data FROM " + table)
	if e != nil {
		return e
	}
	type record struct{ key, data string }
	var records []record
	for rows.Next() {
		var r record
		if e = rows.Scan(&r.key, &r.data); e != nil {
			rows.Close()
			return e
		}
		records = append(records, r)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, r := range records {
		next, e := change(r.key, []byte(r.data))
		if e != nil {
			return fmt.Errorf("%s.%s: %w", table, r.key, e)
		}
		if next == nil {
			continue
		}
		if _, e = tx.Exec("UPDATE "+table+" SET data = ? WHERE key = ?", string(next), r.key); e != nil {
			return e
		}
	}
	return nil
}

// upgradeDrafts 补齐旧作品：台词与乐谱按 Draft.Normalize 补齐；还没有时间线的旧故事作品，
// 把最近一次整篇生成的音频作为一个片段放上时间线，与旧版界面打开时显示的一致。
func upgradeDrafts(tx *sql.Tx) error {
	// 历史表按 pos 从新到旧排列，每个作品取第一条整篇生成；已有分句生成的作品由界面按分句接收，不放整篇音频。
	whole, segmented := map[string]schema.Generation{}, map[string]bool{}
	rows, e := tx.Query("SELECT data FROM history ORDER BY pos, key")
	if e != nil {
		return e
	}
	for rows.Next() {
		var data string
		var g schema.Generation
		if e = rows.Scan(&data); e == nil {
			e = json.Unmarshal([]byte(data), &g)
		}
		if e != nil {
			rows.Close()
			return e
		}
		if g.Segment != nil {
			segmented[g.Settings.ID] = true
		} else if _, seen := whole[g.Settings.ID]; !seen {
			whole[g.Settings.ID] = g
		}
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	return rewriteRows(tx, "drafts", func(_ string, data []byte) ([]byte, error) {
		var d schema.Draft
		if e := json.Unmarshal(data, &d); e != nil {
			return nil, e
		}
		changed := d.Kind == "score" && (d.Score == nil || d.Score.Tracks == nil) ||
			d.Subtitles != nil && slices.ContainsFunc(d.Subtitles.Cues, func(c schema.SubtitleCue) bool { return c.ID == "" })
		d.Normalize()
		story := d.Subtitles != nil || d.Kind == "story" || d.Kind == "subtitle"
		if g, ok := whole[d.ID]; ok && story && d.Timeline == nil && !segmented[d.ID] {
			d.Timeline = &schema.AudioTimeline{Tracks: []schema.AudioLane{{ID: "legacy-" + g.ID, Name: d.Title, Clips: []schema.AudioClip{{ID: g.ID, GenerationID: g.ID, Duration: g.Duration}}}}}
			changed = true
		}
		if !changed {
			return nil, nil
		}
		return json.Marshal(d)
	})
}

// assistantBlocks 把助手旧消息单独存放的工具卡片转成内容块：工具在前、文本在后，与旧版界面的显示顺序一致。
func assistantBlocks(key string, data []byte) ([]byte, error) {
	if key != "assistantSessions" {
		return nil, nil
	}
	type message struct {
		schema.AssistantMessage
		Tools []schema.AssistantToolCard `json:"tools,omitempty"`
	}
	var sessions *struct {
		CurrentID string `json:"currentId"`
		Sessions  []struct {
			ID        string    `json:"id"`
			Title     string    `json:"title"`
			Messages  []message `json:"messages"`
			UpdatedAt time.Time `json:"updatedAt"`
		} `json:"sessions"`
	}
	if e := json.Unmarshal(data, &sessions); e != nil {
		return nil, e
	}
	if sessions == nil {
		return nil, nil
	}
	changed := false
	next := schema.AssistantSessions{CurrentID: sessions.CurrentID, Sessions: make([]schema.AssistantSession, 0, len(sessions.Sessions))}
	for _, s := range sessions.Sessions {
		session := schema.AssistantSession{ID: s.ID, Title: s.Title, UpdatedAt: s.UpdatedAt, Messages: make([]schema.AssistantMessage, 0, len(s.Messages))}
		for _, m := range s.Messages {
			if len(m.Tools) > 0 {
				changed = true
				if len(m.Blocks) == 0 {
					for i := range m.Tools {
						m.Blocks = append(m.Blocks, schema.AssistantBlock{Kind: "tool", Card: &m.Tools[i]})
					}
					if m.Text != "" {
						m.Blocks = append(m.Blocks, schema.AssistantBlock{Kind: "text", Text: m.Text})
					}
				}
			}
			session.Messages = append(session.Messages, m.AssistantMessage)
		}
		next.Sessions = append(next.Sessions, session)
	}
	if !changed {
		return nil, nil
	}
	return json.Marshal(next)
}

// runtimeDir 匹配内核安装目录名“版本-后端-随机数”。
var runtimeDir = regexp.MustCompile(`^v\d+\.\d+\.\d+-[a-z0-9]+-\d+$`)

// runtimeVersion 为旧版下载、未记录版本的内核补记版本：版本取自数据目录下 runtime 中的安装目录名，用户无需重新下载。
func runtimeVersion(tx *sql.Tx, root string) error {
	var path *string
	var version *string
	for key, target := range map[string]**string{"runtimePath": &path, "runtimeVersion": &version} {
		var data string
		e := tx.QueryRow("SELECT data FROM settings WHERE key = ?", key).Scan(&data)
		if e == sql.ErrNoRows {
			continue
		}
		if e != nil {
			return e
		}
		if e = json.Unmarshal([]byte(data), target); e != nil {
			return fmt.Errorf("settings.%s: %w", key, e)
		}
	}
	if path == nil || version != nil {
		return nil
	}
	rel, e := filepath.Rel(filepath.Join(root, "runtime"), *path)
	if e != nil {
		return nil
	}
	dir, _, _ := strings.Cut(filepath.ToSlash(rel), "/")
	if !runtimeDir.MatchString(dir) {
		return nil
	}
	found, _, _ := strings.Cut(dir, "-")
	b, e := json.Marshal(found)
	if e != nil {
		return e
	}
	_, e = tx.Exec("INSERT INTO settings (key, pos, data) VALUES ('runtimeVersion', 0, ?) ON CONFLICT(key) DO UPDATE SET data = excluded.data", string(b))
	return e
}
