/**
 * Decifra um backup (.gpg) no próprio navegador.
 *
 * A chave privada e a senha NUNCA são enviadas ao servidor: o painel só entrega
 * o arquivo ainda cifrado e a decifragem acontece aqui, em memória. O OpenPGP.js
 * é carregado sob demanda (só quando alguém abre a janela de download).
 */

export class PgpError extends Error {}

function isArmored(head: Uint8Array): boolean {
  return new TextDecoder().decode(head.subarray(0, 10)) === "-----BEGIN";
}

export async function decryptBackup(
  encrypted: Uint8Array,
  armoredKey: string,
  passphrase: string,
): Promise<Uint8Array> {
  const openpgp = await import("openpgp");

  let key;
  try {
    key = await openpgp.readPrivateKey({ armoredKey: armoredKey.trim() });
  } catch {
    throw new PgpError("Chave privada inválida. Use o arquivo .asc da chave privada (não a pública).");
  }
  if (!key.isDecrypted()) {
    try {
      key = await openpgp.decryptKey({ privateKey: key, passphrase });
    } catch {
      throw new PgpError("Senha da chave incorreta.");
    }
  }

  let message;
  try {
    message = isArmored(encrypted)
      ? await openpgp.readMessage({ armoredMessage: new TextDecoder().decode(encrypted) })
      : await openpgp.readMessage({ binaryMessage: encrypted });
  } catch {
    throw new PgpError("O arquivo não é uma mensagem PGP válida.");
  }

  try {
    const { data } = await openpgp.decrypt({ message, decryptionKeys: key, format: "binary" });
    return data as Uint8Array;
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (/session key|decryption key/i.test(msg)) {
      throw new PgpError("Esta chave não é a que cifrou o backup.");
    }
    throw new PgpError(`Falha ao decifrar: ${msg || "arquivo corrompido"}`);
  }
}

/** Descompacta gzip com o DecompressionStream nativo do navegador. */
export async function gunzip(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export function saveBlob(name: string, data: Uint8Array): void {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
