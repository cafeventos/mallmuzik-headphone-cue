# Testa o complemento fora do Windows, com um NVDA de mentira e uma placa de mentira.
import sys, types, builtins, importlib.util, struct
builtins._ = lambda s: s
class FakeConf(dict):
    def __init__(self): super().__init__(); self.spec = {}
    def __getitem__(self, k):
        if k not in self:
            dict.__setitem__(self, k, {kk: (False if v.startswith('boolean') else '') for kk, v in self.spec.get(k, {}).items()})
        return dict.__getitem__(self, k)
conf = FakeConf()
class WP:
    def __init__(self, channels, rate, bits):
        self.channels, self.samplesPerSec, self.bitsPerSample = channels, rate, bits
        self.fed = []; self.trim = True
    def feed(self, data, size=None, onDone=None): self.fed.append((bytes(data), onDone))
    def idle(self): pass
    def stop(self): pass
    def startTrimmingLeadingSilence(self, on=True): self.trim = on
said = []
mods = {
 'addonHandler': types.SimpleNamespace(initTranslation=lambda: None),
 'config': types.SimpleNamespace(conf=conf),
 'globalPluginHandler': types.SimpleNamespace(GlobalPlugin=type('GP', (), {'__init__': lambda s: None, 'terminate': lambda s: None})),
 'gui': types.SimpleNamespace(settingsDialogs=types.SimpleNamespace(NVDASettingsDialog=types.SimpleNamespace(categoryClasses=[]))),
 'gui.guiHelper': types.SimpleNamespace(), 'gui.settingsDialogs': types.SimpleNamespace(SettingsPanel=object),
 'nvwave': types.SimpleNamespace(WavePlayer=WP),
 'ui': types.SimpleNamespace(message=lambda m: said.append(m)),
 'wx': types.SimpleNamespace(),
 'logHandler': types.SimpleNamespace(log=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: print('ERR', a), debugWarning=lambda *a, **k: None)),
 'scriptHandler': types.SimpleNamespace(script=lambda **k: (lambda f: f)),
}
mods['gui'].guiHelper = mods['gui.guiHelper']
devices = [('id-realtek', 'Alto-falantes (Realtek)'), ('id-numark', 'Alto-falantes (2- MixTrack Pro)')]
mods['utils'] = types.ModuleType('utils'); mods['utils.mmdevice'] = types.SimpleNamespace(getOutputDevices=lambda: [types.SimpleNamespace(id=i, friendlyName=n) for i, n in devices])
sys.modules.update(mods)
spec = importlib.util.spec_from_file_location('cue', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ok = lambda c, msg: print(('OK  ' if c else 'FAIL'), msg)
m.CHECK_SECONDS = 0

opened = []
class FakeStream:
    def __init__(self, dev, rate, ch):
        self.deviceId, self.rate, self.inChannels, self.outChannels = dev, rate, ch, 4
        self.failed = dev not in [d for d, _ in devices]; self.got = b""; self.stops = 0; self.closed = False
        opened.append(self)
    def usable(self): return not self.failed
    def write(self, pcm):
        if self.failed: return False
        self.got += m._toDeviceChannels(pcm, self.inChannels, self.outChannels); return True
    def stop(self): self.stops += 1
    def close(self): self.closed = True
m.CueStream = FakeStream
plugin = m.GlobalPlugin()

mono = struct.pack('<3h', 100, -200, 300)
ok(struct.unpack('<12h', m._toDeviceChannels(mono, 1, 4)) == (0,0,100,100, 0,0,-200,-200, 0,0,300,300), 'mono: silencio no 1-2, voz no 3-4')
ok(struct.unpack('<12h', m._toDeviceChannels(struct.pack('<4h', 1, 2, 3, 4), 2, 6)) == (0,0,1,2,0,0, 0,0,3,4,0,0), 'estereo numa placa de 6 canais')
ok(m._trimLeading(struct.pack('<4h', 0, 5, -40, 9)) == 4 and m._trimLeading(struct.pack('<2h', 1, -3)) is None, 'corte do silencio do comeco')

p = WP(1, 22050, 16)
p.feed(mono); ok(p.fed[-1][0] == mono and not opened, 'desligado: NVDA normal')

conf['mallmuzikHeadphoneCue']['enabled'] = True
conf['mallmuzikHeadphoneCue']['deviceName'] = 'Alto-falantes (MixTrack Pro)'
p.feed(mono); ok(p.fed[-1][0] == mono, 'no meio da fala nao muda')
p.idle()
done = []
p.feed(struct.pack('<2h', 0, 0) + mono, onDone=lambda: done.append(1))
s = opened[-1]
ok(s.deviceId == 'id-numark' and s.rate == 22050, 'depois da fala: canal na Numark (achada pelo nome)')
ok(p.fed[-1][0] == b'\x00' * 10 and p.fed[-1][1] is not None, 'NVDA toca silencio do mesmo tamanho, com o aviso de fim')
ok(s.got == m._toDeviceChannels(mono, 1, 4), 'voz no fone, sem o silencio do comeco')
ok(p.trim is False, 'corte do NVDA desligado (o silencio e de proposito)')
p.feed(struct.pack('<2h', 0, 0)); ok(s.got.endswith(b'\x00' * 16), 'silencio no meio da fala fica')
p.stop(); ok(s.stops == 1, 'NVDA calou: o fone cala junto')

t = WP(1, 44100, 8); t.feed(b'\x80\x90'); ok(t.fed[-1][0] == b'\x80\x90', 'som de 8 bits: normal (sem risco)')

devices.pop()
p.feed(mono); s.failed = True; p.feed(mono)
ok(p.fed[-1][0] == mono, 'controladora caiu no meio da fala: volta ao normal na hora')
p.idle(); p.feed(mono); ok(p.fed[-1][0] == mono and s.closed, 'sem a Numark: normal, canal fechado')

devices.append(('id-numark2', 'Alto-falantes (3- MixTrack Pro)'))
plugin.script_toggleCue(None); plugin.script_toggleCue(None)
ok(said == ['Headphone cue off', 'Headphone cue on'], 'comando: ' + repr(said))
p.stop(); p.feed(mono); ok(opened[-1].deviceId == 'id-numark2' and p.fed[-1][0] == b'\x00' * 6, 'Numark voltou com outro numero: acha de novo')

m._cafdjOpen = lambda: True
p.idle(); p.feed(mono); ok(p.fed[-1][0] == mono, 'CAF-DJ aberto: este complemento se afasta')

plugin.terminate(); ok(WP.feed is not m._feed, 'desligado: NVDA original')

# Outro complemento (o cafdjFone do CAF-DJ) se instalou por cima e guardou a nossa funcao. Ao sair do
# NVDA, este desliga primeiro: o NVDA tem que continuar falando pelo outro, sem erro.
plugin2 = m.GlobalPlugin(); ours = WP.feed
def otherFeed(self, data, size=None, onDone=None): return ours(self, data, size, onDone)
WP.feed = otherFeed
plugin2.terminate(); ok(WP.feed is otherFeed, 'por baixo de outro complemento: nao desfaz o dele')
p.feed(mono); ok(p.fed[-1][0] == mono, 'desligado, chamado pelo outro: repassa a fala sem erro')
WP.feed = ours  # o outro devolve o que guardou
p.feed(mono); ok(p.fed[-1][0] == mono, 'e continua repassando depois que o outro tambem desliga')
