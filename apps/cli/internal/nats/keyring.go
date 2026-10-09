package nats

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/user"
	"strings"
	"time"

	natsio "github.com/nats-io/nats.go"
)

type keyringRecord struct {
	NewKey     string `json:"new_key"`
	OldKey     string `json:"old_key"`
	EncryptKID string `json:"encrypt_kid"`
}

type keyFileRecord struct {
	Name        string   `json:"name"`
	EncryptKID  string   `json:"encrypt_kid"`
	DecryptKIDs []string `json:"decrypt_kids"`
	SeenAt      string   `json:"seen_at"`
}

// StatusRow is one edge or CLI key file in an encryption status report.
type StatusRow struct {
	Role   string
	Name   string
	State  string
	Detail string
}

// Connect dials NATS, applying TLS when the URL scheme is tls://, then adopts the keyring.
func Connect(servers string, extra ...natsio.Option) (*natsio.Conn, error) {
	opts, err := OptionsForServers(servers, extra...)
	if err != nil {
		return nil, err
	}
	nc, err := natsio.Connect(servers, opts...)
	if err != nil {
		return nil, err
	}
	if err := FinishConnect(nc); err != nil {
		nc.Close()
		return nil, err
	}
	return nc, nil
}

// FinishConnect reads E2E_KEYRING and records this CLI key file when encryption is on.
func FinishConnect(nc *natsio.Conn) error {
	if !Enabled() {
		return nil
	}
	if _, err := syncKeyring(nc); err != nil {
		return err
	}
	return writeKeyFilePresence(nc)
}

func syncKeyring(nc *natsio.Conn) (bool, error) {
	kv, err := keyringKV(nc)
	if err != nil {
		return false, err
	}
	entry, err := kv.Get(keyringKey)
	if errors.Is(err, natsio.ErrKeyNotFound) {
		return false, dropPrevious()
	}
	if err != nil {
		return false, err
	}
	plain, err := OpenKV(keyringBucket, keyringKey, entry.Value())
	if err != nil {
		return false, err
	}
	return adoptRecord(plain)
}

func keyringKV(nc *natsio.Conn) (natsio.KeyValue, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, err
	}
	kv, err := js.KeyValue(keyringBucket)
	if err == nil {
		return kv, nil
	}
	return js.CreateKeyValue(&natsio.KeyValueConfig{Bucket: keyringBucket, History: 1})
}

func keyfilesKV(nc *natsio.Conn) (natsio.KeyValue, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, err
	}
	kv, err := js.KeyValue(keyfilesBucket)
	if err == nil {
		return kv, nil
	}
	return js.CreateKeyValue(&natsio.KeyValueConfig{Bucket: keyfilesBucket, History: 1})
}

func adoptRecord(payload []byte) (bool, error) {
	var record keyringRecord
	if err := json.Unmarshal(payload, &record); err != nil {
		return false, err
	}
	newKey, err := decodeKey(record.NewKey)
	if err != nil {
		return false, err
	}
	oldKey, err := decodeKey(record.OldKey)
	if err != nil {
		return false, err
	}
	var encrypt, extra []byte
	switch record.EncryptKID {
	case kidHex(kidFor(newKey)):
		encrypt, extra = newKey, oldKey
	case kidHex(kidFor(oldKey)):
		encrypt, extra = oldKey, newKey
	default:
		return false, fmt.Errorf("keyring encrypt id does not match either key")
	}
	current := loadRing()
	path := writeKeyPath()
	if current != nil && current.Path != "" {
		path = current.Path
	}
	next := &Ring{Encrypt: encrypt, Previous: extra, Persistent: path != "", Path: path}
	if current != nil && bytesEqual(current.Encrypt, next.Encrypt) && bytesEqual(current.Previous, next.Previous) {
		return false, nil
	}
	if path != "" {
		if err := writeKeyFile(path, next); err != nil {
			return false, err
		}
		next.Persistent = true
	}
	SetRing(next)
	return true, nil
}

func dropPrevious() error {
	current := loadRing()
	if current == nil || len(current.Previous) == 0 {
		return nil
	}
	next := &Ring{Encrypt: current.Encrypt, Persistent: current.Persistent, Path: current.Path}
	if current.Path != "" {
		if err := writeKeyFile(current.Path, next); err != nil {
			return err
		}
		next.Persistent = true
	}
	SetRing(next)
	return nil
}

func writeKeyFilePresence(nc *natsio.Conn) error {
	current := loadRing()
	if current == nil || !current.Persistent || current.Path == "" {
		return nil
	}
	id, err := keyFileID(current.Path)
	if err != nil {
		return nil
	}
	kids := make([]string, 0, len(current.decryptKIDs()))
	for _, kid := range current.decryptKIDs() {
		kids = append(kids, kidHex(kid))
	}
	body, err := json.Marshal(keyFileRecord{
		Name:        cliName(),
		EncryptKID:  kidHex(current.encryptKID()),
		DecryptKIDs: kids,
		SeenAt:      time.Now().UTC().Format(time.RFC3339),
	})
	if err != nil {
		return err
	}
	sealed, err := SealKV(keyfilesBucket, "cli/"+id, body)
	if err != nil {
		return err
	}
	kv, err := keyfilesKV(nc)
	if err != nil {
		return err
	}
	_, err = kv.Put("cli/"+id, sealed)
	return err
}

func cliName() string {
	name := "cli"
	if u, err := user.Current(); err == nil && u.Username != "" {
		name = u.Username
	}
	host, err := os.Hostname()
	if err != nil || host == "" {
		return name
	}
	return name + "@" + host
}

// EncryptionStatus lists edges from ping and CLI key files from E2E_KEYFILES.
func EncryptionStatus(nc *natsio.Conn, timeout time.Duration) ([]StatusRow, error) {
	record, recordErr := readKeyring(nc)
	if recordErr != nil && !errors.Is(recordErr, natsio.ErrKeyNotFound) {
		return nil, recordErr
	}
	var rows []StatusRow
	pongs, err := ListMachinePongs(nc, timeout)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	for _, pong := range pongs {
		seen[pong.MachineID] = true
		rows = append(rows, StatusRow{
			Role:   "edge",
			Name:   pong.MachineID,
			State:  edgeState(record, pong),
			Detail: edgeDetail(pong),
		})
	}
	known, err := ListMachineStateMachines(nc)
	if err == nil {
		for _, id := range known {
			if seen[id] {
				continue
			}
			rows = append(rows, StatusRow{Role: "edge", Name: id, State: "not-answering"})
		}
	}
	files, err := readKeyFiles(nc)
	if err != nil && !errors.Is(err, natsio.ErrKeyNotFound) && !errors.Is(err, natsio.ErrNoKeysFound) {
		return nil, err
	}
	rows = append(rows, files...)
	return rows, nil
}

func edgeState(record *keyringRecord, pong PingResult) string {
	if record == nil {
		current := loadRing()
		if current == nil {
			if pong.EncryptKID == "" {
				return "ready"
			}
			return "not-ready"
		}
		if pong.EncryptKID == kidHex(current.encryptKID()) {
			return "ready"
		}
		return "not-ready"
	}
	newKID := kidOfEncoded(record.NewKey)
	oldKID := kidOfEncoded(record.OldKey)
	if record.EncryptKID == oldKID {
		for _, kid := range pong.DecryptKIDs {
			if kid == newKID {
				return "ready"
			}
		}
		return "not-ready"
	}
	if pong.EncryptKID == newKID {
		return "ready"
	}
	return "not-ready"
}

func edgeDetail(pong PingResult) string {
	if pong.EncryptKID == "" {
		return "no key id"
	}
	detail := "encrypt " + pong.EncryptKID
	if pong.Persist != nil && !*pong.Persist {
		detail += " memory-only"
	}
	return detail
}

func readKeyring(nc *natsio.Conn) (*keyringRecord, error) {
	if !Enabled() {
		return nil, nil
	}
	kv, err := keyringKV(nc)
	if err != nil {
		return nil, err
	}
	entry, err := kv.Get(keyringKey)
	if err != nil {
		return nil, err
	}
	plain, err := OpenKV(keyringBucket, keyringKey, entry.Value())
	if err != nil {
		return nil, err
	}
	var record keyringRecord
	if err := json.Unmarshal(plain, &record); err != nil {
		return nil, err
	}
	return &record, nil
}

func readKeyFiles(nc *natsio.Conn) ([]StatusRow, error) {
	if !Enabled() {
		return nil, nil
	}
	kv, err := keyfilesKV(nc)
	if err != nil {
		return nil, err
	}
	keys, err := kv.Keys()
	if err != nil {
		return nil, err
	}
	record, _ := readKeyring(nc)
	rows := make([]StatusRow, 0, len(keys))
	for _, key := range keys {
		entry, err := kv.Get(key)
		if err != nil {
			continue
		}
		plain, err := OpenKV(keyfilesBucket, key, entry.Value())
		if err != nil {
			continue
		}
		var rec keyFileRecord
		if err := json.Unmarshal(plain, &rec); err != nil {
			continue
		}
		rows = append(rows, StatusRow{
			Role:   "cli",
			Name:   rec.Name,
			State:  cliState(record, rec),
			Detail: "seen " + rec.SeenAt,
		})
	}
	return rows, nil
}

func cliState(record *keyringRecord, rec keyFileRecord) string {
	if record == nil {
		current := loadRing()
		if current != nil && rec.EncryptKID == kidHex(current.encryptKID()) {
			return "ready"
		}
		return "not-ready"
	}
	newKID := kidOfEncoded(record.NewKey)
	oldKID := kidOfEncoded(record.OldKey)
	if record.EncryptKID == oldKID {
		for _, kid := range rec.DecryptKIDs {
			if kid == newKID {
				return "ready"
			}
		}
		return "not-ready"
	}
	if rec.EncryptKID == newKID {
		return "ready"
	}
	return "not-ready"
}

func kidOfEncoded(value string) string {
	key, err := decodeKey(value)
	if err != nil {
		return ""
	}
	return kidHex(kidFor(key))
}

// Rotate starts or joins a key rotation. Retire drops the previous key.
func Rotate(nc *natsio.Conn, retire bool, yes bool, in io.Reader, out io.Writer) error {
	if !Enabled() {
		return fmt.Errorf("payload encryption is off. Use a profile with e2ee enabled. Setup: https://github.com/pudap/puda/blob/main/infra/nats/single-node-e2e/README.md")
	}
	if retire {
		return retireRotation(nc, out)
	}
	current := loadRing()
	if current == nil {
		return fmt.Errorf("encryption is off")
	}
	kv, err := keyringKV(nc)
	if err != nil {
		return err
	}
	entry, err := kv.Get(keyringKey)
	if errors.Is(err, natsio.ErrKeyNotFound) {
		if len(current.Previous) == e2eKeyLen {
			return fmt.Errorf("a previous key is still set; run puda encryption rotate --retire first")
		}
		return startRotation(nc, kv, current, yes, in, out)
	}
	if err != nil {
		return err
	}
	plain, err := OpenKV(keyringBucket, keyringKey, entry.Value())
	if err != nil {
		return err
	}
	if _, err := adoptRecord(plain); err != nil {
		return err
	}
	var record keyringRecord
	if err := json.Unmarshal(plain, &record); err != nil {
		return err
	}
	if record.EncryptKID == kidOfEncoded(record.NewKey) {
		fmt.Fprintln(out, "Rotation already switched to the new key. Run puda encryption rotate --retire after clients have caught up.")
		return PrintStatus(nc, 2*time.Second, out)
	}
	if err := PrintStatus(nc, 2*time.Second, out); err != nil {
		return err
	}
	if !yes && !confirm(in, out, "Switch encryption to the new key?") {
		fmt.Fprintln(out, "Left encryption on the current key.")
		return nil
	}
	return switchRotation(kv, record, out)
}

func startRotation(nc *natsio.Conn, kv natsio.KeyValue, current *Ring, yes bool, in io.Reader, out io.Writer) error {
	nextKey := make([]byte, e2eKeyLen)
	if _, err := rand.Read(nextKey); err != nil {
		return err
	}
	record := keyringRecord{
		NewKey:     encodeKey(nextKey),
		OldKey:     encodeKey(current.Encrypt),
		EncryptKID: kidHex(current.encryptKID()),
	}
	if err := createKeyring(kv, current.Encrypt, record); err != nil {
		if errors.Is(err, natsio.ErrKeyExists) {
			fmt.Fprintln(out, "Another rotation is already in progress.")
			return PrintStatus(nc, 2*time.Second, out)
		}
		return err
	}
	path := writeKeyPath()
	updated := &Ring{Encrypt: current.Encrypt, Previous: nextKey, Persistent: true, Path: path}
	if err := writeKeyFile(path, updated); err != nil {
		return err
	}
	SetRing(updated)
	fmt.Fprintln(out, "Installed the new key for decrypt only. New messages still use the current key.")
	if err := PrintStatus(nc, 2*time.Second, out); err != nil {
		return err
	}
	if !yes && !confirm(in, out, "Switch encryption to the new key?") {
		fmt.Fprintln(out, "Left encryption on the current key.")
		return nil
	}
	return switchRotation(kv, record, out)
}

func switchRotation(kv natsio.KeyValue, record keyringRecord, out io.Writer) error {
	oldKey, err := decodeKey(record.OldKey)
	if err != nil {
		return err
	}
	newKey, err := decodeKey(record.NewKey)
	if err != nil {
		return err
	}
	record.EncryptKID = kidHex(kidFor(newKey))
	if err := putKeyring(kv, oldKey, record); err != nil {
		return err
	}
	if _, err := adoptRecord(mustJSON(record)); err != nil {
		return err
	}
	fmt.Fprintln(out, "Switched encryption to the new key. The previous key still opens old frames.")
	return nil
}

func retireRotation(nc *natsio.Conn, out io.Writer) error {
	kv, err := keyringKV(nc)
	if err != nil {
		return err
	}
	if err := kv.Delete(keyringKey); err != nil && !errors.Is(err, natsio.ErrKeyNotFound) {
		return err
	}
	if files, err := keyfilesKV(nc); err == nil {
		if keys, err := files.Keys(); err == nil {
			for _, key := range keys {
				_ = files.Delete(key)
			}
		}
	}
	if err := dropPrevious(); err != nil {
		return err
	}
	fmt.Fprintln(out, "Retired the previous key.")
	return nil
}

func sealKeyring(wrapKey []byte, record keyringRecord) ([]byte, error) {
	body := mustJSON(record)
	previous := loadRing()
	SetRing(&Ring{Encrypt: wrapKey})
	defer SetRing(previous)
	return SealKV(keyringBucket, keyringKey, body)
}

func createKeyring(kv natsio.KeyValue, wrapKey []byte, record keyringRecord) error {
	sealed, err := sealKeyring(wrapKey, record)
	if err != nil {
		return err
	}
	_, err = kv.Create(keyringKey, sealed)
	return err
}

func putKeyring(kv natsio.KeyValue, wrapKey []byte, record keyringRecord) error {
	sealed, err := sealKeyring(wrapKey, record)
	if err != nil {
		return err
	}
	_, err = kv.Put(keyringKey, sealed)
	return err
}

func PrintStatus(nc *natsio.Conn, timeout time.Duration, out io.Writer) error {
	rows, err := EncryptionStatus(nc, timeout)
	if err != nil {
		return err
	}
	if len(rows) == 0 {
		fmt.Fprintln(out, "No edges or CLI key files have reported.")
		return nil
	}
	for _, row := range rows {
		fmt.Fprintf(out, "%s %s %s", row.State, row.Role, row.Name)
		if row.Detail != "" {
			fmt.Fprintf(out, " (%s)", row.Detail)
		}
		fmt.Fprintln(out)
	}
	return nil
}

func confirm(in io.Reader, out io.Writer, prompt string) bool {
	fmt.Fprintf(out, "%s [y/N] ", prompt)
	buf := make([]byte, 32)
	n, _ := in.Read(buf)
	answer := strings.TrimSpace(strings.ToLower(string(buf[:n])))
	return answer == "y" || answer == "yes"
}

func encodeKey(key []byte) string {
	return base64.StdEncoding.EncodeToString(key)
}

func mustJSON(v any) []byte {
	body, err := json.Marshal(v)
	if err != nil {
		return []byte("{}")
	}
	return body
}
