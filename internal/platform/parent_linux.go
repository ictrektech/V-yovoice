//go:build linux

package platform

import (
	"os/exec"
	"syscall"
)

// Linux 容器中的服务异常退出时，内核停止其计算子进程。
func setParentDeath(c *exec.Cmd) { c.SysProcAttr.Pdeathsig = syscall.SIGKILL }
