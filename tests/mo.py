# Gera o nvda.mo (gettext) a partir de pares ingles -> portugues.
import struct, sys
LANGS = {
 "pt_BR": {
  "Headphone Cue": "Pré-escuta no fone",
  "Speak only in the controller &headphones (channels 3 and 4)": "Falar só no &fone da controladora (canais 3 e 4)",
  "{name} (not connected)": "{name} (desconectada)",
  "DJ &controller:": "&Controladora de DJ:",
  "Turns the voice in the controller headphones on or off": "Liga ou desliga a voz do NVDA no fone da controladora",
  "Headphone Cue for MallMuzik": "Pré-escuta no fone para o MallMuzik",
  "Headphone cue off": "Pré-escuta no fone desligada",
  "Headphone cue on": "Pré-escuta no fone ligada",
  "Headphone cue on, but the controller is not connected": "Pré-escuta no fone ligada, mas a controladora não está conectada",
 },
 "es": {
  "Headphone Cue": "Preescucha en auriculares",
  "Speak only in the controller &headphones (channels 3 and 4)": "Hablar solo en los &auriculares de la controladora (canales 3 y 4)",
  "{name} (not connected)": "{name} (desconectada)",
  "DJ &controller:": "&Controladora de DJ:",
  "Turns the voice in the controller headphones on or off": "Activa o desactiva la voz de NVDA en los auriculares de la controladora",
  "Headphone Cue for MallMuzik": "Preescucha en auriculares para MallMuzik",
  "Headphone cue off": "Preescucha en auriculares desactivada",
  "Headphone cue on": "Preescucha en auriculares activada",
  "Headphone cue on, but the controller is not connected": "Preescucha en auriculares activada, pero la controladora no está conectada",
 },
}
lang = sys.argv[3] if len(sys.argv) > 3 else "pt_BR"
pairs = LANGS[lang]
src = open(sys.argv[1], encoding='utf-8').read()
missing = [k for k in pairs if f'_("{k}")' not in src]
assert not missing, missing
import re
used = set(re.findall(r'_\("((?:[^"\\]|\\.)*)"\)', src))
assert used <= set(pairs), used - set(pairs)
entries = {"": "Content-Type: text/plain; charset=UTF-8\n"}
entries.update(pairs)
keys = sorted(entries)
ids = [k.encode() for k in keys]; strs = [entries[k].encode() for k in keys]
n = len(keys); ko = 28; to = ko + n * 8; data = to + n * 8
idtab, strtab, blob = [], [], b""
for b in ids:
    idtab.append((len(b), data + len(blob))); blob += b + b"\0"
for b in strs:
    strtab.append((len(b), data + len(blob))); blob += b + b"\0"
out = struct.pack("<7I", 0x950412de, 0, n, ko, to, 0, 0)
out += b"".join(struct.pack("<2I", *x) for x in idtab) + b"".join(struct.pack("<2I", *x) for x in strtab) + blob
open(sys.argv[2], "wb").write(out)
import gettext
t = gettext.GNUTranslations(open(sys.argv[2], "rb"))
assert t.gettext("Headphone cue on") == pairs["Headphone cue on"]
print("mo ok", lang, n - 1, "frases")
