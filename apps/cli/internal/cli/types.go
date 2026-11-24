package cli

import (
	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

type immediateCommandSender func(
	nc *nats.Conn,
	machineID, runID, userID, username string,
	timeoutSeconds int,
	store *db.Store,
) (*puda.NATSMessage, error)

type immediateMachineCommandConfig struct {
	name      string
	short     string
	label     string
	sender    immediateCommandSender
	runIDFlag *string
	long      string
}
