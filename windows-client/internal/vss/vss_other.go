//go:build !windows

package vss

import (
	"context"
	"errors"
)

func Create(_ context.Context, volumes []string, _ func(Snapshot)) *Set {
	s := &Set{Snaps: map[string]Snapshot{}, Failed: map[string]string{}}
	for _, v := range volumes {
		s.Failed[v] = "VSS só existe no Windows"
	}
	return s
}

func Delete(context.Context, []string) error { return nil }

func (s *Set) Release(context.Context) error { return nil }

func VolumeDevice(string) (string, error) { return "", errors.New("só no Windows") }
