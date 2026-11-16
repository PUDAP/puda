package cli

import (
	"fmt"
	"time"

	compatibility "github.com/PUDAP/puda"
	"github.com/PUDAP/puda/apps/cli/internal/update"
	"github.com/spf13/cobra"
)

// writeUpdateCompatibility warns before the existing confirmation and replacement
// flow. Unknown policy/discovery never silently becomes a compatibility approval.
func writeUpdateCompatibility(cmd *cobra.Command, targetTag string) {
	w := cmd.ErrOrStderr()
	fmt.Fprintf(w, "Python SDK update preflight for CLI %q: responding edges only (2s collection window); offline or late edges are not evaluated. Advisory only.\n", targetTag)
	policy, err := update.FetchCompatibility(cmd.Context(), targetTag)
	if err != nil {
		fmt.Fprintf(w, "Python SDK compatibility unknown: target release metadata unavailable: %v (no bundled or main fallback; advisory only).\n", err)
	} else if policy.Evaluate(targetTag, "0.0.0").Status == compatibility.Unknown {
		fmt.Fprintf(w, "Python SDK compatibility unknown: target CLI %q has no valid release policy (advisory only).\n", targetTag)
	}
	conn, err := prepareConnection()
	if err != nil {
		fmt.Fprintf(w, "Python SDK compatibility not checked: fleet discovery unavailable: %v (advisory only).\n", err)
		return
	}
	writeFleetCompatibility(w, conn.Servers, 2*time.Second, targetTag, policy, Version)
}
