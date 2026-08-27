package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/PUDAP/puda/apps/loadgen/internal/config"
	"github.com/PUDAP/puda/apps/loadgen/internal/loadgen"
	"github.com/PUDAP/puda/apps/loadgen/internal/metrics"
)

func main() {
	cfg, err := config.Parse(os.Args[1:])
	if errors.Is(err, flag.ErrHelp) {
		printUsage()
		return
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "puda-loadgen: %v\n\n", err)
		printUsage()
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if cfg.Duration > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, cfg.Duration)
		defer cancel()
	}

	m := metrics.New()
	var server *http.Server
	if cfg.MetricsAddress != "" {
		server = &http.Server{
			Addr: cfg.MetricsAddress, Handler: m.Handler(),
			ReadHeaderTimeout: 5 * time.Second, WriteTimeout: 10 * time.Second,
			IdleTimeout: 30 * time.Second,
		}
		go func() {
			log.Printf("metrics listening on %s (/metrics, /summary)", cfg.MetricsAddress)
			if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Printf("metrics server: %v", err)
				m.Error("metrics_server")
			}
		}()
	}

	log.Printf("starting puda-loadgen: edges=%d mode=%s scenario=%s servers=%v", cfg.Edges, cfg.Mode, cfg.Scenario, config.RedactedServers(cfg.NATSServers))
	runner := loadgen.New(cfg, m)
	if err := runner.Run(ctx); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
		log.Printf("load generation failed: %v", err)
		m.Error("runner")
		writeSummary(cfg.ReportPath, m)
		os.Exit(1)
	}
	if server != nil {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		_ = server.Shutdown(shutdownCtx)
		cancel()
	}
	writeSummary(cfg.ReportPath, m)
}

func writeSummary(path string, m *metrics.Metrics) {
	data, err := json.MarshalIndent(m.Summary(), "", "  ")
	if err != nil {
		log.Printf("encode summary: %v", err)
		return
	}
	fmt.Println(string(data))
	if path == "" {
		return
	}
	if err := os.WriteFile(path, append(data, '\n'), 0o644); err != nil {
		log.Printf("write report %s: %v", path, err)
	}
}

func printUsage() {
	fmt.Print(`puda-loadgen - scalable PUDA edge workload generator

Usage:
  puda-loadgen [flags]

Core flags:
  --edges N                    virtual edge count (default 1000)
  --prefix NAME                machine ID prefix (default load)
  --start-index N              first machine index (default 1)
  --nats-servers URLS          comma-separated NATS URLs
  --mode MODE                  full-fidelity or multiplexed
  --connections N              multiplexed connection-pool size
  --scenario NAME              connections, consumers, heartbeat, telemetry, soak
  --duration DURATION          zero means until interrupted
  --ramp-duration DURATION     spread connection creation over this duration
  --heartbeat-interval DURATION
  --position-interval DURATION
  --health-interval DURATION
  --queue-stream NAME          default COMMAND_QUEUE
  --immediate-stream NAME      default COMMAND_IMMEDIATE
  --setup-concurrency N        consumer setup workers (default 64)
  --queue-fetch-wait DURATION  default 30s
  --command-interval DURATION  queue + immediate command interval; zero disables
  --cleanup-consumers BOOL     delete test consumers on shutdown (default true)
  --metrics-address ADDRESS    default 127.0.0.1:9090; empty disables
  --report PATH                optional final JSON report

Modes:
  full-fidelity  one NATS connection per edge; supports every scenario
  multiplexed    a connection pool shared by virtual IDs; telemetry only
`)
}
