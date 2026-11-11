# Headphone Cue for MallMuzik
# Makes NVDA speak only in the DJ controller's headphones (channels 3 and 4).
#
# How it works: NVDA keeps playing on its normal device, but silence of the same length (so the
# speech timing, say all and indexes stay exactly the same). The real sound (voice, beeps, sounds)
# goes to a stream of its own on the controller's sound card, opened with all of the card's
# channels: silence on 1 and 2 (master, the audience) and the voice on 3 and 4 (headphones).
# Windows mixes it with the DJ software (VirtualDJ), which must share the card (not ASIO/exclusive).
#
# Safety: if the controller is missing or fails, the option is off, or CAF-DJ is open (it already
# does this by itself), NVDA plays normally. Changes happen between utterances.

import array
import collections
import ctypes
import re
import threading
import time
from ctypes import POINTER, byref, c_ubyte, c_uint32, c_void_p, wintypes

import addonHandler
import config
import globalPluginHandler
import gui
import nvwave
import ui
import wx
from gui import guiHelper
from gui.settingsDialogs import SettingsPanel
from logHandler import log
from scriptHandler import script

addonHandler.initTranslation()

SECTION = "mallmuzikHeadphoneCue"
config.conf.spec[SECTION] = {
	"enabled": "boolean(default=False)",
	"deviceId": "string(default='')",
	"deviceName": "string(default='')",
}

CAFDJ_PIPE = "\\\\.\\pipe\\CAF-DJ-voz"
CHECK_SECONDS = 2.0
RETRY_SECONDS = 3.0
SILENCE = 32  # 16-bit level under which the start of an utterance is cut (as NVDA does)

_originals = {}
_lock = threading.Lock()
_cache = {"at": 0.0, "route": None}
_failedAt = {}  # device -> when it last failed


# --- Which device -------------------------------------------------------------------------------


def _outputDevices():
	try:
		from utils.mmdevice import getOutputDevices
	except ImportError:
		return []
	try:
		return [(d.id, d.friendlyName) for d in getOutputDevices()]
	except Exception:
		log.debugWarning("Headphone cue: could not list devices", exc_info=True)
		return []


def _plainName(name):
	# "Speakers (2- MixTrack Pro)" and "Speakers (MixTrack Pro)" are the same controller.
	return re.sub(r"(^|[ (])\d+- ", r"\1", name or "").strip().lower()


def _findDevice():
	wantedId = config.conf[SECTION]["deviceId"]
	wantedName = _plainName(config.conf[SECTION]["deviceName"])
	devices = _outputDevices()
	for devId, _name in devices:
		if wantedId and devId == wantedId:
			return devId
	for devId, name in devices:
		if wantedName and _plainName(name) == wantedName:
			return devId
	return None


def _cafdjOpen():
	try:
		kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	except AttributeError:
		return False
	if kernel32.WaitNamedPipeW(CAFDJ_PIPE, 1):
		return True
	return ctypes.get_last_error() != 2  # 2 = no such pipe; anything else: it exists (busy)


def desiredRoute(force=False):
	"""The controller's endpoint ID when the voice should go to its headphones, else None."""
	now = time.monotonic()
	with _lock:
		if not force and now - _cache["at"] < CHECK_SECONDS:
			return _cache["route"]
	route = None
	try:
		if config.conf[SECTION]["enabled"] and not _cafdjOpen():
			route = _findDevice()
			if route and now - _failedAt.get(route, -1e9) < RETRY_SECONDS:
				route = None
	except Exception:
		log.debugWarning("Headphone cue: route check failed", exc_info=True)
	with _lock:
		_cache["at"] = now
		_cache["route"] = route
	return route


# --- The stream on the controller (WASAPI, shared mode) -----------------------------------------


def _toDeviceChannels(pcm, inChannels, outChannels):
	"""16-bit PCM: silence on every channel except 3 and 4, which get the voice (mono on both)."""
	frame = 2 * inChannels
	frames = len(pcm) // frame
	out = bytearray(frames * outChannels * 2)
	step = outChannels * 2
	right = 2 if inChannels > 1 else 0
	for k in range(2):
		left = pcm[k : frames * frame : frame]
		out[4 + k :: step] = left
		out[6 + k :: step] = pcm[right + k : frames * frame : frame] if right else left
	return bytes(out)


def _trimLeading(pcm):
	"""Index (in bytes) of the first sound in 16-bit PCM, or None if it is all silence."""
	samples = array.array("h")
	samples.frombytes(pcm[: len(pcm) // 2 * 2])
	for i, v in enumerate(samples):
		if v > SILENCE or v < -SILENCE:
			return i * 2
	return None


if hasattr(ctypes, "windll"):
	import comtypes
	from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

	class WAVEFORMATEX(ctypes.Structure):
		_pack_ = 1
		_fields_ = [
			("wFormatTag", wintypes.WORD),
			("nChannels", wintypes.WORD),
			("nSamplesPerSec", wintypes.DWORD),
			("nAvgBytesPerSec", wintypes.DWORD),
			("nBlockAlign", wintypes.WORD),
			("wBitsPerSample", wintypes.WORD),
			("cbSize", wintypes.WORD),
		]

	class WAVEFORMATEXTENSIBLE(ctypes.Structure):
		_pack_ = 1
		_fields_ = [
			("Format", WAVEFORMATEX),
			("wValidBitsPerSample", wintypes.WORD),
			("dwChannelMask", wintypes.DWORD),
			("SubFormat", GUID),
		]

	class IAudioClient(IUnknown):
		_iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
		_methods_ = [
			COMMETHOD([], HRESULT, "Initialize",
				(["in"], wintypes.DWORD, "ShareMode"),
				(["in"], wintypes.DWORD, "StreamFlags"),
				(["in"], ctypes.c_longlong, "hnsBufferDuration"),
				(["in"], ctypes.c_longlong, "hnsPeriodicity"),
				(["in"], c_void_p, "pFormat"),
				(["in"], c_void_p, "AudioSessionGuid")),
			COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "pNumBufferFrames")),
			COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(ctypes.c_longlong), "phnsLatency")),
			COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "pNumPaddingFrames")),
			COMMETHOD([], HRESULT, "IsFormatSupported",
				(["in"], wintypes.DWORD, "ShareMode"),
				(["in"], c_void_p, "pFormat"),
				(["out"], POINTER(c_void_p), "ppClosestMatch")),
			COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(c_void_p), "ppDeviceFormat")),
			COMMETHOD([], HRESULT, "GetDevicePeriod",
				(["out"], POINTER(ctypes.c_longlong), "phnsDefaultDevicePeriod"),
				(["out"], POINTER(ctypes.c_longlong), "phnsMinimumDevicePeriod")),
			COMMETHOD([], HRESULT, "Start"),
			COMMETHOD([], HRESULT, "Stop"),
			COMMETHOD([], HRESULT, "Reset"),
			COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "eventHandle")),
			COMMETHOD([], HRESULT, "GetService",
				(["in"], POINTER(GUID), "riid"),
				(["out"], POINTER(POINTER(IUnknown)), "ppv")),
		]

	class IAudioRenderClient(IUnknown):
		_iid_ = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
		_methods_ = [
			COMMETHOD([], HRESULT, "GetBuffer",
				(["in"], c_uint32, "NumFramesRequested"),
				(["out"], POINTER(POINTER(c_ubyte)), "ppData")),
			COMMETHOD([], HRESULT, "ReleaseBuffer",
				(["in"], c_uint32, "NumFramesWritten"),
				(["in"], wintypes.DWORD, "dwFlags")),
		]

	KSDATAFORMAT_SUBTYPE_PCM = GUID("{00000001-0000-0010-8000-00aa00389b71}")
	AUDCLNT_SHAREMODE_SHARED = 0
	AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
	AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
	CLSCTX_ALL = 23


class CueStream:
	"""One NVDA player's sound on the controller. All COM work happens in its own thread."""

	def __init__(self, deviceId, rate, inChannels):
		self.deviceId = deviceId
		self.rate = rate
		self.inChannels = inChannels
		self.outChannels = 0
		self.blockAlign = 0
		self.queue = collections.deque()
		self.queued = 0  # bytes
		self.flush = False
		self.failed = False
		self.ready = threading.Event()
		self.wake = threading.Event()
		self.running = True
		self.openedAt = time.monotonic()
		self.thread = threading.Thread(target=self._run, name="mallmuzikHeadphoneCue", daemon=True)
		self.thread.start()

	def usable(self):
		"""Open and working. Opening happens in the background: NVDA never waits for the card."""
		if self.failed:
			return False
		if not self.ready.is_set():
			if time.monotonic() - self.openedAt > 3.0:
				log.warning("Headphone cue: the controller took too long to open; voice stays normal")
				self.failed = True
				# Windows is still busy with this card (e.g. right after turning on): wait longer.
				_failedAt[self.deviceId] = time.monotonic() + 30.0
			return False
		return True

	def write(self, pcm):
		"""Queue 16-bit PCM of this player. False if the stream cannot play it."""
		if not self.usable():
			return False
		data = _toDeviceChannels(pcm, self.inChannels, self.outChannels)
		with _lock:
			if self.queued > self.rate * self.blockAlign * 6:
				self.failed = True  # the controller stopped taking sound: back to normal
				log.warning("Headphone cue: the controller stopped playing; voice back to normal")
				return False
			self.queue.append(data)
			self.queued += len(data)
		self.wake.set()
		return True

	def stop(self):
		with _lock:
			self.queue.clear()
			self.queued = 0
			self.flush = True
		self.wake.set()

	def close(self):
		self.running = False
		self.wake.set()

	def _open(self):
		from pycaw.utils import AudioUtilities

		device = AudioUtilities.GetDeviceEnumerator().GetDevice(self.deviceId)
		client = device.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)
		mixPtr = client.GetMixFormat()
		try:
			mix = ctypes.cast(mixPtr, POINTER(WAVEFORMATEX)).contents
			channels = mix.nChannels
			mask = 0
			if mix.wFormatTag == 0xFFFE:
				mask = ctypes.cast(mixPtr, POINTER(WAVEFORMATEXTENSIBLE)).contents.dwChannelMask
		finally:
			ctypes.windll.ole32.CoTaskMemFree(c_void_p(mixPtr))
		if channels < 4:
			raise RuntimeError("the controller has only %d channels (no 3 and 4)" % channels)
		fmt = WAVEFORMATEXTENSIBLE()
		fmt.Format.wFormatTag = 0xFFFE
		fmt.Format.nChannels = channels
		fmt.Format.nSamplesPerSec = self.rate
		fmt.Format.wBitsPerSample = 16
		fmt.Format.nBlockAlign = channels * 2
		fmt.Format.nAvgBytesPerSec = self.rate * channels * 2
		fmt.Format.cbSize = 22
		fmt.wValidBitsPerSample = 16
		fmt.dwChannelMask = mask
		fmt.SubFormat = KSDATAFORMAT_SUBTYPE_PCM
		client.Initialize(
			AUDCLNT_SHAREMODE_SHARED,
			AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
			2_000_000,  # 200 ms of buffer
			0,
			ctypes.addressof(fmt),
			None,
		)
		render = client.GetService(IAudioRenderClient._iid_).QueryInterface(IAudioRenderClient)
		bufferFrames = client.GetBufferSize()
		return client, render, bufferFrames, channels

	def _run(self):
		comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
		client = render = None
		try:
			client, render, bufferFrames, channels = self._open()
			self.outChannels = channels
			self.blockAlign = channels * 2
			log.info(f"Headphone cue: voice in the controller headphones ({channels} channels, {self.rate} Hz)")
		except Exception:
			log.warning("Headphone cue: could not open the controller", exc_info=True)
			self.failed = True
			_failedAt[self.deviceId] = time.monotonic()
			self.ready.set()
			comtypes.CoUninitialize()
			return
		if self.failed:  # took too long: NVDA already gave up on it
			comtypes.CoUninitialize()
			return
		self.ready.set()
		started = False
		pending = b""
		try:
			while self.running and not self.failed:
				self.wake.wait(0.005)
				self.wake.clear()
				with _lock:
					flush, self.flush = self.flush, False
				if flush:
					pending = b""
					if started:
						client.Stop()
						client.Reset()
						started = False
				free = bufferFrames - client.GetCurrentPadding()
				while free > 0:
					if not pending:
						with _lock:
							if not self.queue:
								break
							pending = self.queue.popleft()
							self.queued -= len(pending)
					frames = min(free, len(pending) // self.blockAlign)
					if frames <= 0:
						pending = b""
						continue
					ptr = render.GetBuffer(frames)
					ctypes.memmove(ptr, pending, frames * self.blockAlign)
					render.ReleaseBuffer(frames, 0)
					pending = pending[frames * self.blockAlign :]
					free -= frames
					if not started:
						client.Start()
						started = True
		except Exception:
			log.warning("Headphone cue: the controller stopped (disconnected?); voice back to normal", exc_info=True)
			self.failed = True
			_failedAt[self.deviceId] = time.monotonic()
		finally:
			try:
				if started:
					client.Stop()
			except Exception:
				pass
			render = client = None
			comtypes.CoUninitialize()


# --- NVDA's players -----------------------------------------------------------------------------


def _bytesOf(data, size):
	if isinstance(data, (bytes, bytearray, memoryview)):
		return bytes(data) if size is None else bytes(data)[:size]
	ptr = data.value if isinstance(data, ctypes.c_void_p) else data
	if not ptr or not size:
		return b""
	return ctypes.string_at(ptr, size)


def _streamFor(player):
	"""This player's stream on the controller, created or closed at utterance boundaries."""
	stream = getattr(player, "_cueStream", None)
	if getattr(player, "_cueBoundary", True):
		player._cueBoundary = False
		route = desiredRoute() if player.bitsPerSample == 16 and player.channels in (1, 2) else None
		if stream and (stream.failed or stream.deviceId != route):
			stream.close()
			stream = None
		if route and not stream:
			stream = CueStream(route, player.samplesPerSec, player.channels)  # opens in the background
		player._cueStream = stream
	return stream if stream and stream.usable() else None


def _feed(self, data, size=None, onDone=None):
	try:
		stream = _streamFor(self)
		if stream:
			pcm = _bytesOf(data, size)
			length = len(pcm)
			if getattr(self, "_cueTrimming", True):
				start = _trimLeading(pcm)
				pcm = b"" if start is None else pcm[start:]
				self._cueTrimming = start is None
			if not pcm or stream.write(pcm):
				# NVDA plays silence of the same length: same rhythm, nothing on the speakers.
				self.startTrimmingLeadingSilence(False)
				return _originals["feed"](self, b"\x00" * length, None, onDone)
	except Exception:
		log.error("Headphone cue: error, playing normally", exc_info=True)
	return _originals["feed"](self, data, size, onDone)


def _boundary(self, stopped):
	self._cueBoundary = True
	self._cueTrimming = True
	stream = getattr(self, "_cueStream", None)
	if stream and stopped:
		stream.stop()


def _idle(self):
	result = _originals["idle"](self)
	_boundary(self, False)
	return result


def _stop(self):
	result = _originals["stop"](self)
	_boundary(self, True)
	return result


# --- Settings and command -----------------------------------------------------------------------


class HeadphoneCuePanel(SettingsPanel):
	# Translators: title of the settings category
	title = _("Headphone Cue")

	def makeSettings(self, settingsSizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.enabledBox = helper.addItem(
			# Translators: checkbox in the settings
			wx.CheckBox(self, label=_("Speak only in the controller &headphones (channels 3 and 4)")),
		)
		self.enabledBox.SetValue(config.conf[SECTION]["enabled"])
		self._devices = _outputDevices()
		names = [name for _devId, name in self._devices]
		savedName = config.conf[SECTION]["deviceName"]
		if savedName and _plainName(savedName) not in [_plainName(n) for n in names]:
			# Translators: shown next to a controller that is not connected now
			names.append(_("{name} (not connected)").format(name=savedName))
			self._devices.append((config.conf[SECTION]["deviceId"], savedName))
		# Translators: label of the device list
		self.deviceList = helper.addLabeledControl(_("DJ &controller:"), wx.Choice, choices=names)
		selection = 0
		for i, (devId, name) in enumerate(self._devices):
			if devId == config.conf[SECTION]["deviceId"] or _plainName(name) == _plainName(savedName):
				selection = i
				break
		if names:
			self.deviceList.SetSelection(selection)

	def onSave(self):
		config.conf[SECTION]["enabled"] = self.enabledBox.GetValue()
		index = self.deviceList.GetSelection()
		if 0 <= index < len(self._devices):
			devId, name = self._devices[index]
			config.conf[SECTION]["deviceId"] = devId
			config.conf[SECTION]["deviceName"] = name
		_failedAt.clear()
		desiredRoute(force=True)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		for name, func in (("feed", _feed), ("idle", _idle), ("stop", _stop)):
			_originals[name] = getattr(nvwave.WavePlayer, name)
			setattr(nvwave.WavePlayer, name, func)
		gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(HeadphoneCuePanel)

	def terminate(self):
		for name, func in _originals.items():
			setattr(nvwave.WavePlayer, name, func)
		_originals.clear()
		try:
			gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(HeadphoneCuePanel)
		except ValueError:
			pass
		super().terminate()

	@script(
		# Translators: description of the command in Input Gestures
		description=_("Turns the voice in the controller headphones on or off"),
		# Translators: category in Input Gestures
		category=_("Headphone Cue for MallMuzik"),
	)
	def script_toggleCue(self, gesture):
		on = not config.conf[SECTION]["enabled"]
		config.conf[SECTION]["enabled"] = on
		_failedAt.clear()
		route = desiredRoute(force=True)
		if not on:
			# Translators: spoken when turned off
			ui.message(_("Headphone cue off"))
		elif route:
			# Translators: spoken when turned on
			ui.message(_("Headphone cue on"))
		else:
			# Translators: spoken when on but the controller is not connected
			ui.message(_("Headphone cue on, but the controller is not connected"))
