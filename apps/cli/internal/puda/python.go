package puda

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// EnsurePythonModule checks if a Python module can be imported, and if not,
// attempts to install it using pip from the libs/drivers directory.
func EnsurePythonModule(moduleName string) error {
	// First, try to import the module to see if it's available
	checkCmd := exec.Command("python3", "-c", fmt.Sprintf("import %s", moduleName))
	if err := checkCmd.Run(); err == nil {
		// Module is available, nothing to do
		return nil
	}

	// Module not found, try to install dependencies
	fmt.Fprintf(os.Stderr, "Python module '%s' not found. Attempting to install with pip...\n", moduleName)

	// Find the libs/drivers directory to install the package in editable mode
	driversPath, err := findDriversPath()
	if err != nil {
		return fmt.Errorf("failed to find drivers directory: %w", err)
	}

	// Install the package in editable mode using pip
	pipCmd := exec.Command("pip", "install", "-e", driversPath)
	pipCmd.Stdout = os.Stderr
	pipCmd.Stderr = os.Stderr
	if err := pipCmd.Run(); err != nil {
		return fmt.Errorf("failed to install Python package with 'pip install -e %s': %w", driversPath, err)
	}

	// Verify the module is now available
	checkCmd = exec.Command("python3", "-c", fmt.Sprintf("import %s", moduleName))
	if err := checkCmd.Run(); err != nil {
		return fmt.Errorf("module '%s' still not available after installation. You may need to run 'pip install -e %s' manually", moduleName, driversPath)
	}

	fmt.Fprintf(os.Stderr, "Successfully installed Python package.\n")
	return nil
}

// findDriversPath searches for the libs/drivers directory
func findDriversPath() (string, error) {
	// Start from the current working directory
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}

	// Walk up the directory tree looking for libs/drivers
	for {
		driversPath := filepath.Join(dir, "libs", "drivers")
		if _, err := os.Stat(driversPath); err == nil {
			// Check if it has a pyproject.toml
			pyprojectPath := filepath.Join(driversPath, "pyproject.toml")
			if _, err := os.Stat(pyprojectPath); err == nil {
				return driversPath, nil
			}
		}

		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached filesystem root
			break
		}
		dir = parent
	}

	return "", fmt.Errorf("libs/drivers directory not found")
}

// ShowPublicMethods executes a Python script to display all public methods of a class
// with their signatures and docstrings.
// modulePath is the Python import path (e.g., "puda_drivers.machines")
// className is the class name (e.g., "First" or "Biologic")
func ShowPublicMethods(modulePath string, className string) error {
	// Ensure Python module is available
	if err := EnsurePythonModule("puda_drivers"); err != nil {
		return fmt.Errorf("failed to ensure Python module: %w", err)
	}

	// Python script with show_public_methods function
	pythonScript := fmt.Sprintf(`import inspect

def show_public_methods(cls):
    # Get all members that are functions and don't start with _
    methods = [(name, func) for name, func in inspect.getmembers(cls, predicate=inspect.isfunction) if not name.startswith('_')]
    for i, (name, func) in enumerate(methods):
        print(f"{name}{inspect.signature(func)}")
        doc = inspect.getdoc(func)
        if doc:
            # Indent each line of the docstring
            for line in doc.split('\n'):
                print(f"    {line}")
        # Add blank line between methods (but not after the last one)
        if i < len(methods) - 1:
            print()

from %s import %s
show_public_methods(%s)
`, modulePath, className, className)

	// Execute Python script
	pythonCmd := exec.Command("python3", "-c", pythonScript)
	output, err := pythonCmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("error running Python help: %w\nOutput: %s", err, string(output))
	}

	fmt.Print(string(output))
	return nil
}
