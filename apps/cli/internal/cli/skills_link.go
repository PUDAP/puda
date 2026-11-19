package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// localSkill is one skill folder (containing SKILL.md) from a local source.
type localSkill struct {
	name string
	path string
}

// skillLinkConflict is a link target occupied by something other than a symlink.
type skillLinkConflict struct {
	target string
	source string
}

// resolveLocalSkillsSource reports whether arg names a local directory.
// Path-like arguments (./, ../, /, ~) must exist; anything else that is not an
// existing directory is treated as a remote source for npx.
func resolveLocalSkillsSource(arg string) (string, bool, error) {
	path := arg
	if path == "~" || strings.HasPrefix(path, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", false, err
		}
		path = filepath.Join(home, strings.TrimPrefix(path, "~"))
	}
	pathLike := filepath.IsAbs(path) || path == "." || path == ".." ||
		strings.HasPrefix(path, "./") || strings.HasPrefix(path, "../") || path != arg
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		if pathLike {
			return "", false, fmt.Errorf("local skills path %q is not a directory", arg)
		}
		return "", false, nil
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", false, err
	}
	return abs, true, nil
}

func hasSkillMd(dir string) bool {
	info, err := os.Stat(filepath.Join(dir, "SKILL.md"))
	return err == nil && !info.IsDir()
}

func childSkills(dir string) []localSkill {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var skills []localSkill
	for _, entry := range entries {
		child := filepath.Join(dir, entry.Name())
		if info, err := os.Stat(child); err == nil && info.IsDir() && hasSkillMd(child) {
			skills = append(skills, localSkill{name: entry.Name(), path: child})
		}
	}
	return skills
}

// discoverLocalSkills accepts a skill folder, a folder of skills, or a
// repository root whose skills live in skills/.
func discoverLocalSkills(root string) ([]localSkill, error) {
	if hasSkillMd(root) {
		return []localSkill{{name: filepath.Base(root), path: root}}, nil
	}
	if skills := childSkills(root); len(skills) > 0 {
		return skills, nil
	}
	if skills := childSkills(filepath.Join(root, "skills")); len(skills) > 0 {
		return skills, nil
	}
	return nil, fmt.Errorf("no skills found in %s: expected <name>/SKILL.md or skills/<name>/SKILL.md", root)
}

// agentSkillDirs returns the shared skills directory first, then the skills
// directories of agents that are installed on this host.
func agentSkillDirs() (string, []string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", nil, err
	}
	shared := filepath.Join(home, ".agents", "skills")
	hermes := os.Getenv("HERMES_HOME")
	if hermes == "" {
		hermes = filepath.Join(home, ".hermes")
	}
	var agents []string
	for _, agentHome := range []string{hermes, filepath.Join(home, ".claude"), filepath.Join(home, ".cursor")} {
		if info, err := os.Stat(agentHome); err == nil && info.IsDir() {
			agents = append(agents, filepath.Join(agentHome, "skills"))
		}
	}
	return shared, agents, nil
}

// linkSkill points target at source, replacing only an existing symlink.
func linkSkill(target, source string) (bool, error) {
	if info, err := os.Lstat(target); err == nil {
		if info.Mode()&os.ModeSymlink == 0 {
			return false, nil
		}
		if err := os.Remove(target); err != nil {
			return false, err
		}
	} else if !os.IsNotExist(err) {
		return false, err
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return false, err
	}
	if err := os.Symlink(source, target); err != nil {
		return false, fmt.Errorf("symlink %s -> %s: %w (on Windows, enable Developer Mode or run as administrator)", target, source, err)
	}
	return true, nil
}

// linkLocalSkills symlinks every skill under the given local roots into the
// shared skills directory and each installed agent's skills directory.
func linkLocalSkills(out io.Writer, roots []string) (int, error) {
	shared, agents, err := agentSkillDirs()
	if err != nil {
		return 0, err
	}
	var skills []localSkill
	for _, root := range roots {
		found, err := discoverLocalSkills(root)
		if err != nil {
			return 0, err
		}
		skills = append(skills, found...)
	}
	sort.SliceStable(skills, func(i, j int) bool { return skills[i].name < skills[j].name })

	var conflicts []skillLinkConflict
	linked := 0
	for _, skill := range skills {
		canonical := filepath.Join(shared, skill.name)
		ok, err := linkSkill(canonical, skill.path)
		if err != nil {
			return linked, err
		}
		if !ok {
			conflicts = append(conflicts, skillLinkConflict{target: canonical, source: skill.path})
			continue
		}
		fmt.Fprintf(out, "symlinked %s -> %s\n", canonical, skill.path)
		linked++
		for _, dir := range agents {
			target := filepath.Join(dir, skill.name)
			ok, err := linkSkill(target, canonical)
			if err != nil {
				return linked, err
			}
			if !ok {
				conflicts = append(conflicts, skillLinkConflict{target: target, source: canonical})
				continue
			}
			fmt.Fprintf(out, "symlinked %s -> %s\n", target, canonical)
		}
	}
	if len(conflicts) > 0 {
		lines := make([]string, len(conflicts))
		for i, c := range conflicts {
			lines[i] = fmt.Sprintf("  %s is a copied folder, not a symlink; remove it and re-run to link %s", c.target, c.source)
		}
		return linked, fmt.Errorf("%d skill target(s) not linked:\n%s", len(conflicts), strings.Join(lines, "\n"))
	}
	return linked, nil
}
