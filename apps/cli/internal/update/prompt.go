package update

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
)

// promptConfirm asks a yes/no question on stdin.
func promptConfirm(cmd *cobra.Command, question string, defaultYes bool) bool {
	out := cmd.OutOrStdout()
	suffix := "(y/N):"
	if defaultYes {
		suffix = "(Y/n)"
	}
	fmt.Fprintf(out, "%s %s ", question, suffix)

	reader := bufio.NewReader(os.Stdin)
	line, err := reader.ReadString('\n')
	if err != nil && line == "" {
		return false
	}
	ans := strings.ToLower(strings.TrimSpace(line))
	if ans == "" {
		return defaultYes
	}
	return ans == "y" || ans == "yes"
}
