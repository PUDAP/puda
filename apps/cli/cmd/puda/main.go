package main

import (
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/cli"
)

func main() {
	if err := cli.Execute(); err != nil {
		os.Exit(1)
	}
}

