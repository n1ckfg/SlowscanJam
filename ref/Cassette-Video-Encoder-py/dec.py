from pillcase.pillcase import Pillcase

class VC(object):

	def __init__(self):
		self.config = {
			"buffersize": 512,
			"clearInterval": 50,
			"overScan": 0.82,
			"hOffset": 0.06525,
			"pulseLength": (0.2 / 1000),
			"lineWidth": 2.5,
			"brightness": 1,
			"saturation": 1,
			"blend": True,
			"hFreq": 225.0,
			"vFreq": 3
		}

		self.buffersize = self.config["buffersize"]

		self.sig = {
			"LMin": 0.0,
			"LMax": 1.0,

			"CMin": -1.0,
			"CMax": 1.0,
		}

		self.hPhase = 0
		self.vPhase = 0

		self.pulse = {
			"time": 0,
			"timeout": 0,
			"luma": 0,
			"lumaPrev": 0,
			"chroma": 0,
			"chromaPrev": 0,
			"changed": False,
			"ready": False
		}

		self.timing = {
			"time": 0,
			"lastV": 0,
			"lastH": 0,
		}

		self.field = 0
		self.chromaField = 0

		self.chromaDelay = []
		self.chromaDelayIndex = 0

		self.lines = []
		self.currLine = {
			"x1": 0,
			"y": 0,
			"maxPhase": 0,
			"colors": []
		}
		self.lastClear = 0
		self.clearInterval = self.config["clearInterval"]

		self.overScan = self.config["overScan"]
		self.hOffset = self.config["hOffset"]

		self.pulseLength = self.config["pulseLength"]

		self.canvas = config.canvas
		self.ctx = self.canvas.getContext("2d")

		self.width = self.canvas.width
		self.height = self.canvas.height

		self.lineWidth = self.config["lineWidth"]
		self.blend = self.config["blend"]
		self.brightness = self.config["brightness"]
		self.saturation = self.config["saturation"]

		requestAnimationFrame(() => self.draw())

		self.audioCtx = new window.AudioContext()
		self.sampleRate = self.audioCtx.sampleRate

		self.audioInput = None
		self.decoder = None

		self.hFreqTarget = 1.0 / self.config["hFreq"] * self.sampleRate
		self.vFreqTarget = 1.0 / self.config["vFreq"] * self.sampleRate
		self.hFreq = self.hFreqTarget
		self.vFreq = self.vFreqTarget

		navigator.mediaDevices.getUserMedia(
			{
				audio: {
					echoCancellation: False,
					noiseSuppression: False,
					autoGainControl: False,
					channelCount: 2
				}
			})
			.then(stream =>
			{
				self.audioInput = self.audioCtx.createMediaStreamSource(stream)

				self.decoder = self.audioCtx.createScriptProcessor(self.buffersize, 2, 2)

				self.decoder.onaudioprocess = event => self.process(event)

				self.audioInput.connect(self.decoder)
				self.decoder.connect(self.audioCtx.destination) // Needed to work around webkit bug
			})
			.catch(console.error)

	def hPhaseToX(hPhase, vPhase, field):
		return ((hPhase - self.hOffset) / self.overScan) * self.width

	def vPhaseToY(hPhase, vPhase, field):
		return (vPhase + (field / self.vFreq) * self.hFreq * 0.5) * self.height

	def YCbCrToRGB(y, cb, cr):
		r = y + 45 * cr / 32
		g = y - (11 * cb + 23 * cr) / 32
		b = y + 113 * cb / 64

		return [r, g, b]

	def process(event):
		lSamples = event.inputBuffer.getChannelData(0)
		cSamples = event.inputBuffer.getChannelData(1)

		sampleRate = self.sampleRate

		s = self.sig
		p = self.pulse

		blank = False

		for i in range(0, len(lSamples)):
			self.timing.time += 1

			lSample = lSamples[i] + Math.random() * 0.01 - 0.005
			cSample = cSamples[i] + Math.random() * 0.01 - 0.005


			if (lSample < s.LMin) s.LMin = lSample
			if (lSample > s.LMax) s.LMax = lSample

			s.LMin *= 1.0 - (1.0 / sampleRate)
			s.LMax *= 1.0 - (1.0 / sampleRate)

			if (s.LMin > -0.025) s.LMin = -0.025
			if (s.LMax < 0.025) s.LMax = 0.025


			if (cSample < s.CMin) s.CMin = cSample
			if (cSample > s.CMax) s.CMax = cSample

			s.CMin *= 1.0 - (1.0 / sampleRate)
			s.CMax *= 1.0 - (1.0 / sampleRate)

			if (s.CMin > -0.05) s.CMin = -0.05
			if (s.CMax < 0.05) s.CMax = 0.05


			luma = (lSample * 2.0 - s.LMin) / (s.LMax - s.LMin) * self.brightness * 255
			chroma = (cSample * 2.0 - s.CMin) / (s.CMax - s.CMin) * self.saturation * 255
			chromaLast = self.chromaDelay[self.chromaDelayIndex] || 0

			if (self.chromaDelayIndex < sampleRate / 10.0):
				self.chromaDelay[self.chromaDelayIndex] = chroma
				self.chromaDelayIndex++

			chroma = chroma - 128
			chromaLast = chromaLast - 128

			if (self.chromaField == 0):
				[r, g, b] = self.YCbCrToRGB(luma, chromaLast, chroma)
			else:
				[r, g, b] = self.YCbCrToRGB(luma, chroma, chromaLast)

			if (self.currLine.colors.length < 1024):
				self.currLine.colors.append(
					{
						"phase": self.hPhase,
						"r": Math.max(Math.min(Math.round(r), 255), 0),
						"g": Math.max(Math.min(Math.round(g), 255), 0),
						"b": Math.max(Math.min(Math.round(b), 255), 0)
					}
				)

			self.currLine.maxPhase = self.hPhase

			self.hPhase += 1.0 / self.hFreq
			self.vPhase += 1.0 / self.vFreq

			self.currLine.x2 = self.hPhaseToX(self.hPhase, self.vPhase, self.field)

			if (((s.LMax - s.LMin) > 0.1) and ((s.CMax - s.CMin) > 0.1)):
				if (lSample < s.LMin * 0.5):
					p.luma = -1
				elif (lSample > s.LMax * 0.5):
					p.luma = 1
				else:
					p.luma = 0

				if (cSample < s.CMin * 0.5):
					p.chroma = -1
				elif (cSample > s.CMax * 0.5):
					p.chroma = 1
				else:
					p.chroma = 0

				if ((p.luma != p.lumaPrev) or (p.chroma != p.chromaPrev)):
					p.time = 0
					p.lumaPrev = p.luma
					p.chromaPrev = p.chroma
					p.changed = True

				if ((p.luma != 0) and (p.chroma != 0)):
					p.time += 1.0 / sampleRate

					if ((p.time > self.pulseLength * 0.5) and (p.changed == True)):
						p.changed = False

						if (p.ready == False):
							p.ready = True
							p.timeout = self.pulseLength * 1.25
						else:
							p.ready = False
							blank = True

							if ((self.timing.time - self.timing.lastH < self.hFreqTarget * 1.5) and	(self.timing.time - self.timing.lastH > self.hFreqTarget * 0.5)):
								self.hFreq = self.hFreq * 0.9 + (self.timing.time - self.timing.lastH) * 0.1

							self.timing.lastH = self.timing.time

							self.hPhase = 0
							self.chromaDelayIndex = 0

							if (p.luma > 0):
								self.chromaField = 0
							else:
								self.chromaField = 1

							if (p.luma != p.chroma):
								if ((self.timing.time - self.timing.lastV < self.vFreqTarget * 1.5) and	(self.timing.time - self.timing.lastV > self.vFreqTarget * 0.5)):
									self.vFreq = self.vFreq * 0.75 + (self.timing.time - self.timing.lastV) * 0.25

								self.timing.lastV = self.timing.time

								self.vPhase = 0
								self.chromaField = 1

								if (p.luma > 0):
									self.field = 0
								else:
									self.field = 1

				if (p.ready == True):
					p.timeout -= 1.0 / sampleRate
					if (p.timeout <= 0):
						p.ready = False
			else:
				p.luma = p.lumaPrev = 0
				p.chroma = p.chromaPrev = 0
				p.changed = False
				p.ready = False

			self.hFreq = self.hFreq * (1.0 - 1.0 / sampleRate) + self.hFreqTarget * (1.0 / sampleRate)
			self.vFreq = self.vFreq * (1.0 - 1.0 / sampleRate) + self.vFreqTarget * (1.0 / sampleRate)

			if (self.hPhase >= 1.0):
				blank = True

				self.hPhase -= 1.0
				self.chromaDelayIndex = 0

				if (self.chromaField == 1):
					self.chromaField = 0
				else:
					self.chromaField = 1

			if (self.vPhase >= 1.0):
				blank = True

				self.vPhase -= 1.0

				if (self.field == 0):
					self.field = 1
				else:
					self.field = 0

			if (blank == True):
				if ((self.lines.length < 1024) and (self.currLine.colors.length > 5) and (self.currLine.maxPhase > 0)):
					self.lines.append(self.currLine)

				self.currLine =
				{
					x1: self.hPhaseToX(self.hPhase, self.vPhase, self.field),
					y: self.vPhaseToY(self.hPhase, self.vPhase, self.field),
					maxPhase: 0,
					colors: []
				}

				blank = False

	def draw():
		requestAnimationFrame(() => self.draw())

		if (Date.now() - self.lastClear > self.clearInterval): 
			self.ctx.fillStyle = 'rgba(0,0,0,0.05)'
			self.ctx.globalCompositeOperation = 'source-over'
			self.ctx.fillRect(0, 0, self.width, self.height)
			self.lastClear = Date.now()

		if (self.blend == True):
			self.ctx.globalCompositeOperation = 'screen'

		self.ctx.lineWidth = self.lineWidth

		foreach (line in self.lines):
			grd = self.ctx.createLinearGradient(line.x1, line.y, line.x2, line.y)

			foreach (color in line.colors):
				grd.addColorStop(color.phase / line.maxPhase, 'rgb(' + color.r + ',' + color.g + ',' + color.b + ')')

			self.ctx.beginPath()

			self.ctx.moveTo(line.x1 + Math.random() * 2.0 - 1.0, line.y + Math.random() * 2.0 - 1.0)
			self.ctx.lineTo(line.x2 + Math.random() * 2.0 - 1.0, line.y + Math.random() * 2.0 - 1.0)

			self.ctx.strokeStyle = grd

			self.ctx.stroke()

		self.lines = []
