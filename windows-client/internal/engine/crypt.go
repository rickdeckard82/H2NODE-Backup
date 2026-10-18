package engine

import (
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/ProtonMail/go-crypto/openpgp"
	"github.com/ProtonMail/go-crypto/openpgp/packet"
)

// Recipient é a chave pública do servidor (só cifra; a privada nunca sai do worker).
type Recipient struct {
	entities    openpgp.EntityList
	Fingerprint string // 40 hex maiúsculos, como o gpg mostra
}

// ParsePublicKey lê a chave pública armorada recebida do servidor.
func ParsePublicKey(armored string) (*Recipient, error) {
	el, err := openpgp.ReadArmoredKeyRing(strings.NewReader(armored))
	if err != nil {
		return nil, fmt.Errorf("chave pública GPG inválida: %w", err)
	}
	if len(el) != 1 {
		return nil, fmt.Errorf("esperava 1 chave pública, veio %d", len(el))
	}
	fp := strings.ToUpper(fmt.Sprintf("%X", el[0].PrimaryKey.Fingerprint))
	return &Recipient{entities: el, Fingerprint: fp}, nil
}

// NormalizeFingerprint tira espaços e põe em maiúsculas (o painel mostra com ou sem espaços).
func NormalizeFingerprint(fp string) string {
	return strings.ToUpper(strings.ReplaceAll(strings.TrimSpace(fp), " ", ""))
}

// encryptConfig: AES-256, sem compressão (o conteúdo já é .tar.gz ou arquivo do
// usuário) e sem AEAD — o mesmo formato do agente Linux (gpg --compress-algo none
// --cipher-algo AES256), que o gpg do worker decifra.
var encryptConfig = &packet.Config{
	DefaultCipher:          packet.CipherAES256,
	DefaultHash:            0,
	DefaultCompressionAlgo: packet.CompressionNone,
}

// Encrypt devolve um WriteCloser: o que for escrito sai cifrado em `out`. Close
// finaliza a mensagem OpenPGP (não fecha `out`).
func (r *Recipient) Encrypt(out io.Writer) (io.WriteCloser, error) {
	if r == nil || len(r.entities) == 0 {
		return nil, errors.New("sem chave pública")
	}
	return openpgp.Encrypt(out, r.entities, nil, &openpgp.FileHints{IsBinary: true}, encryptConfig)
}
