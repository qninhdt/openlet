package main

import (
	"errors"
	"flag"
	"io"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/temporal"
)

func backfillOptions(args []string) (*temporal.BackfillOptions, error) {
	if len(args) == 0 {
		return nil, nil
	}
	if args[0] != "--backfill-processing" {
		return nil, errors.New("unknown command")
	}
	var input temporal.BackfillOptions
	var after string
	flags := flag.NewFlagSet("backfill-processing", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.StringVar(&input.Mode, "mode", "missing", "")
	flags.BoolVar(&input.Apply, "apply", false, "")
	flags.IntVar(&input.Limit, "limit", 100, "")
	flags.StringVar(&after, "after", uuid.Nil.String(), "")
	if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || input.Mode != "missing" && input.Mode != "rebuild-index" || input.Limit < 1 || input.Limit > 1000 {
		return nil, errors.New("invalid backfill options")
	}
	var err error
	input.After, err = uuid.Parse(after)
	if err != nil {
		return nil, errors.New("invalid backfill cursor")
	}
	return &input, nil
}
