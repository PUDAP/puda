package cli

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"

	"github.com/spf13/cobra"
)

// defaultSkillsRepos selects an explicit ref or the CLI's matching release.
func defaultSkillsRepos(ref string) ([]string, error) {
	if ref != "" {
		// The installer treats /tree/<ref>/<subpath> as single path segments.
		// Reject ambiguous or unsafe refs instead of escaping or rewriting them.
		valid := regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)
		if !valid.MatchString(ref) || strings.Contains(ref, "..") || strings.HasSuffix(ref, ".") || strings.HasSuffix(ref, ".lock") {
			return nil, fmt.Errorf("invalid --ref %q: use a branch or tag with letters, digits, dots, underscores or hyphens, without slashes, '..', a trailing dot or '.lock'", ref)
		}
		return []string{"https://github.com/PUDAP/puda/tree/" + ref + "/skills"}, nil
	}
	version := strings.TrimPrefix(Version, "v")
	release := regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$`)
	pseudo := regexp.MustCompile(`[.-][0-9]{14}-[0-9a-f]+$`)
	lower := strings.ToLower(version)
	if !release.MatchString(version) || pseudo.MatchString(version) || strings.Contains(lower, "snapshot") || strings.Contains(lower, "dev") || strings.Contains(lower, "dirty") {
		return nil, fmt.Errorf("CLI version %q is a development build; use --ref main explicitly for development skills, or install a released CLI", Version)
	}
	return []string{
		"https://github.com/PUDAP/puda/tree/v" + strings.TrimPrefix(Version, "v") + "/skills",
	}, nil
}

// skillsCmd is the parent for skills-related subcommands
var skillsCmd = &cobra.Command{
	Use:   "skills",
	Short: "Official PUDA skills for AI agents",
	Long:  `Install and update the official PUDA skills for AI agents. Requires Node.js and npx.`,
}

// skillsInstallCmd installs skills from a repo
var skillsInstallCmd = &cobra.Command{
	Use:   "install [repo...]",
	Short: "Install skills from a repository",
	Long: `Install skills from repositories

With no arguments, installs PUDAP/puda's skills subtree at the installed CLI's
release tag. --ref <git-reference> selects a branch or tag (for example main
or v0.1.6); development binaries require an explicit ref. Refs must be simple
names without slashes, URL metacharacters, or Git revision expressions.
Missing tags/subtrees fail without falling back to main.

Additional repositories are passed unchanged to npx after the defaults.
Each source is installed globally with: npx skills add <source> -y -g
No blanket skills update is run. Existing same-name skills are replaced.`,
	RunE: runSkillsInstall,
}

// skillsUpdateCmd re-adds selected sources, including migration from the old repo.
var skillsUpdateCmd = &cobra.Command{
	Use:   "update [repo...]",
	Short: "Update agent skills",
	Long: `Reinstall the release-matched official PUDA skills.

This also migrates same-name global skills previously installed from PUDAP/skills
to PUDAP/puda's skills subtree. --ref selects a branch or tag instead of the
installed release (for example --ref main or --ref v0.1.6). Refs must be simple
names without slashes, URL metacharacters, or Git revision expressions.
Optional repositories are re-added unchanged, after the defaults. Unspecified
custom skills and project-local installs are not refreshed or removed.
Legacy-only skills (such as puda-memory) are not automatically removed.
No blanket npx skills update is run.`,
	RunE: runSkillsUpdate,
}

func init() {
	skillsInstallCmd.Flags().String("ref", "", "Use a simple Git branch or tag instead of the installed CLI release (e.g. main or v0.1.6)")
	skillsUpdateCmd.Flags().String("ref", "", "Use a simple Git branch or tag instead of the installed CLI release (e.g. main or v0.1.6)")
	skillsCmd.AddCommand(skillsInstallCmd)
	skillsCmd.AddCommand(skillsUpdateCmd)
	rootCmd.AddCommand(skillsCmd)
}

func ensureNpx() error {
	if _, err := exec.LookPath("npx"); err != nil {
		fmt.Fprintf(os.Stderr, "Error: npx not found. Skills requires Node.js.\n")
		fmt.Fprintf(os.Stderr, "Install Node.js from: https://nodejs.org/en/download\n")
		return err
	}
	return nil
}

func runNpx(args ...string) error {
	c := exec.Command("npx", args...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin
	return c.Run()
}

// Installs globally; the current directory does not change the selected scope.
func installSkillsGlobally(repos []string) error {
	if err := ensureNpx(); err != nil {
		return err
	}
	for _, repo := range repos {
		if err := runNpx("skills", "add", repo, "-y", "-g"); err != nil {
			return fmt.Errorf("skills add %s: %w", repo, err)
		}
	}
	return nil
}

func runSkillsInstall(cmd *cobra.Command, args []string) error {
	ref, err := cmd.Flags().GetString("ref")
	if err != nil {
		return err
	}
	if cmd.Flags().Changed("ref") && ref == "" {
		return fmt.Errorf("invalid --ref: reference must not be empty")
	}
	repos, err := defaultSkillsRepos(ref)
	if err != nil {
		return err
	}
	repos = append(repos, args...)
	if err := installSkillsGlobally(repos); err != nil {
		return err
	}
	fmt.Fprintf(cmd.OutOrStdout(), "Skills installed globally. Same-name skills replace old sources; legacy-only skills and project-local installs are unchanged.\n")
	return nil
}

func runSkillsUpdate(cmd *cobra.Command, args []string) error {
	// Re-add the official source to migrate old PUDAP/skills lock entries.
	// Never blanket-update unrelated skills or override the release pin.
	return runSkillsInstall(cmd, args)
}
