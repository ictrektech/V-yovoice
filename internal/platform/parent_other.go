//go:build !linux && !windows

package platform

import "os/exec"

func setParentDeath(*exec.Cmd) {}
