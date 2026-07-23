package cli

import (
	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

type immediateCommandSender func(
	js nats.JetStreamContext,
	dispatcher *pudanats.ResponseDispatcher,
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
}
