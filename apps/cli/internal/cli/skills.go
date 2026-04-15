package cli

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

// defaultSkillsRepos are installed by "puda skills install" and always included
var defaultSkillsRepos = []string{
	"PUDAP/skills",
	"streamlit/agent-skills",
}

// skillsCmd is the parent for skills-related subcommands
var skillsCmd = &cobra.Command{
	Use:   "skills",
	Short: "Manage puda agent skills",
	Long:  `Install and update agent skills for this project. Requires Node.js and npx.`,
}

// skillsInstallCmd installs skills from a repo
var skillsInstallCmd = &cobra.Command{
	Use:   "install [repo...]",
	Short: "Install skills from a repository",
	Long: `Install skills from repositories

With no arguments, installs default PUDAP/skills and streamlit/agent-skills.
With one or more arguments, installs each given repo plus the defaults.

Runs:
  npx skills add <repo> --yes
  npx skills update --yes`,
	RunE: runSkillsInstall,
}

// skillsUpdateCmd refreshes skills from repo and syncs AGENTS.md
var skillsUpdateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update agent skills",
	Long: `Refresh installed skills from their repos

Runs: npx skills update`,
	RunE: runSkillsUpdate,
}

func init() {
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

// Installs and syncs skills in the current working directory.
func installSkillsInCwd(repos []string) error {
	if err := ensureNpx(); err != nil {
		return err
	}
	for _, repo := range repos {
		if err := runNpx("skills", "add", repo, "-y", "-g"); err != nil {
			return fmt.Errorf("skills add %s: %w", repo, err)
		}
	}
	if err := runNpx("skills", "update", "-y", "-g"); err != nil {
		return fmt.Errorf("skills update failed: %w", err)
	}
	return nil
}

func runSkillsInstall(cmd *cobra.Command, args []string) error {
	repos := make([]string, 0, len(defaultSkillsRepos)+len(args))
	repos = append(repos, defaultSkillsRepos...)
	repos = append(repos, args...)
	if err := installSkillsInCwd(repos); err != nil {
		return err
	}
	fmt.Fprintf(cmd.OutOrStdout(), "Skills installed and synced successfully.\n")
	return nil
}

func runSkillsUpdate(cmd *cobra.Command, args []string) error {
	if err := ensureNpx(); err != nil {
		return err
	}
	if err := runNpx("skills", "update", "-y"); err != nil {
		return fmt.Errorf("skills update failed: %w", err)
	}
	return nil
}
