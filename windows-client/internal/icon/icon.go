// Package icon desenha o ícone do Pulse Backup (quadrado azul com a linha de pulso)
// sem depender de arquivos: PNG para o executável e ICO para a bandeja.
package icon

import (
	"bytes"
	"encoding/binary"
	"image"
	"image/color"
	"image/png"
	"math"
)

var (
	brand   = color.RGBA{0x1a, 0x4f, 0xd8, 0xff} // brand-600 do painel
	running = color.RGBA{0xd9, 0x77, 0x06, 0xff} // amber-600: backup em andamento
	failed  = color.RGBA{0xe1, 0x1d, 0x48, 0xff} // rose-600: último backup falhou
	white   = color.RGBA{0xff, 0xff, 0xff, 0xff}
)

// pulse em coordenadas 0..1
var pulse = [][2]float64{{0.14, 0.55}, {0.36, 0.55}, {0.45, 0.30}, {0.56, 0.76}, {0.65, 0.45}, {0.70, 0.55}, {0.86, 0.55}}

// Draw desenha o ícone com `size` pixels; state: "" | "running" | "failed".
func Draw(size int, state string) *image.RGBA {
	bg := brand
	switch state {
	case "running":
		bg = running
	case "failed":
		bg = failed
	}
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	s := float64(size)
	r := s * 0.22 // raio do canto
	// fundo arredondado com anti-aliasing simples (4x4 amostras por pixel)
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			cov := 0.0
			for sy := 0; sy < 4; sy++ {
				for sx := 0; sx < 4; sx++ {
					px, py := float64(x)+(float64(sx)+0.5)/4, float64(y)+(float64(sy)+0.5)/4
					if inRoundRect(px, py, s, r) {
						cov++
					}
				}
			}
			if cov > 0 {
				a := cov / 16
				img.SetRGBA(x, y, color.RGBA{uint8(float64(bg.R) * a), uint8(float64(bg.G) * a), uint8(float64(bg.B) * a), uint8(255 * a)})
			}
		}
	}
	// linha de pulso branca, espessura proporcional
	w := math.Max(1.2, s*0.075)
	for i := 0; i+1 < len(pulse); i++ {
		x0, y0 := pulse[i][0]*s, pulse[i][1]*s
		x1, y1 := pulse[i+1][0]*s, pulse[i+1][1]*s
		stroke(img, x0, y0, x1, y1, w)
	}
	return img
}

func inRoundRect(x, y, s, r float64) bool {
	cx := math.Min(math.Max(x, r), s-r)
	cy := math.Min(math.Max(y, r), s-r)
	return (x-cx)*(x-cx)+(y-cy)*(y-cy) <= r*r
}

// stroke pinta o segmento com largura w (cobertura por distância ao segmento).
func stroke(img *image.RGBA, x0, y0, x1, y1, w float64) {
	minX, maxX := int(math.Floor(math.Min(x0, x1)-w)), int(math.Ceil(math.Max(x0, x1)+w))
	minY, maxY := int(math.Floor(math.Min(y0, y1)-w)), int(math.Ceil(math.Max(y0, y1)+w))
	for y := minY; y <= maxY; y++ {
		for x := minX; x <= maxX; x++ {
			if !(image.Point{x, y}.In(img.Rect)) {
				continue
			}
			d := distToSegment(float64(x)+0.5, float64(y)+0.5, x0, y0, x1, y1)
			a := math.Min(1, math.Max(0, w/2+0.5-d))
			if a <= 0 {
				continue
			}
			c := img.RGBAAt(x, y)
			img.SetRGBA(x, y, color.RGBA{
				blend(c.R, white.R, a), blend(c.G, white.G, a), blend(c.B, white.B, a), blend(c.A, 255, a),
			})
		}
	}
}

func blend(a, b uint8, t float64) uint8 { return uint8(float64(a)*(1-t) + float64(b)*t) }

func distToSegment(px, py, x0, y0, x1, y1 float64) float64 {
	dx, dy := x1-x0, y1-y0
	t := ((px-x0)*dx + (py-y0)*dy) / (dx*dx + dy*dy)
	t = math.Max(0, math.Min(1, t))
	return math.Hypot(px-(x0+t*dx), py-(y0+t*dy))
}

// PNG do ícone.
func PNG(size int, state string) []byte {
	var b bytes.Buffer
	_ = png.Encode(&b, Draw(size, state))
	return b.Bytes()
}

// ICO com uma imagem PNG dentro (aceito pelo Windows Vista em diante).
func ICO(size int, state string) []byte {
	p := PNG(size, state)
	var b bytes.Buffer
	dim := uint8(size)
	if size >= 256 {
		dim = 0
	}
	binary.Write(&b, binary.LittleEndian, struct{ Reserved, Type, Count uint16 }{0, 1, 1})
	binary.Write(&b, binary.LittleEndian, struct {
		W, H, Colors, Reserved uint8
		Planes, BPP            uint16
		Size, Offset           uint32
	}{dim, dim, 0, 0, 1, 32, uint32(len(p)), 6 + 16})
	b.Write(p)
	return b.Bytes()
}
