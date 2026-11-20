// Package icon desenha o ícone do H2NODE Backup (três nós ligados em triângulo,
// como no logotipo) sem depender de arquivos: PNG para o executável e ICO para a bandeja.
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
	brand   = color.RGBA{0x0b, 0x10, 0x22, 0xff} // fundo do logotipo
	running = color.RGBA{0xd9, 0x77, 0x06, 0xff} // amber-600: backup em andamento
	failed  = color.RGBA{0xe1, 0x1d, 0x48, 0xff} // rose-600: último backup falhou
	white   = color.RGBA{0xff, 0xff, 0xff, 0xff}
	edge    = color.RGBA{0xa5, 0xb4, 0xfc, 0xff} // lilás das ligações
	violet  = color.RGBA{0xa7, 0x8b, 0xfa, 0xff} // nós da esquerda
	cyan    = color.RGBA{0x22, 0xd3, 0xee, 0xff} // nó da ponta
)

// nós em coordenadas 0..1 (mesma geometria do logo-*.svg, viewBox 48)
var nodes = [3][2]float64{{15.0 / 48, 12.0 / 48}, {15.0 / 48, 36.0 / 48}, {35.0 / 48, 24.0 / 48}}

// Draw desenha o ícone com `size` pixels; state: "" | "running" | "failed".
// Nos estados de alerta o fundo muda de cor e o desenho fica branco, para ler bem na bandeja.
func Draw(size int, state string) *image.RGBA {
	bg, line, left, tip := brand, edge, violet, cyan
	switch state {
	case "running":
		bg, line, left, tip = running, white, white, white
	case "failed":
		bg, line, left, tip = failed, white, white, white
	}
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	s := float64(size)
	r := s * 0.25 // raio do canto (rx 12 de 48)
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
	// ligações (espessura proporcional; mínimo legível em 16 px) e depois os nós por cima
	w := math.Max(1.2, s*3/48)
	for i := 0; i < 3; i++ {
		a, b := nodes[i], nodes[(i+1)%3]
		stroke(img, a[0]*s, a[1]*s, b[0]*s, b[1]*s, w, line)
	}
	rad := math.Max(1.6, s*5/48)
	disc(img, nodes[0][0]*s, nodes[0][1]*s, rad, left)
	disc(img, nodes[1][0]*s, nodes[1][1]*s, rad, left)
	disc(img, nodes[2][0]*s, nodes[2][1]*s, rad, tip)
	return img
}

// disc pinta um círculo cheio com borda suavizada.
func disc(img *image.RGBA, cx, cy, rad float64, col color.RGBA) {
	for y := int(math.Floor(cy - rad - 1)); y <= int(math.Ceil(cy+rad+1)); y++ {
		for x := int(math.Floor(cx - rad - 1)); x <= int(math.Ceil(cx+rad+1)); x++ {
			if !(image.Point{x, y}.In(img.Rect)) {
				continue
			}
			d := math.Hypot(float64(x)+0.5-cx, float64(y)+0.5-cy)
			a := math.Min(1, math.Max(0, rad+0.5-d))
			if a > 0 {
				paint(img, x, y, col, a)
			}
		}
	}
}

func paint(img *image.RGBA, x, y int, col color.RGBA, a float64) {
	c := img.RGBAAt(x, y)
	img.SetRGBA(x, y, color.RGBA{blend(c.R, col.R, a), blend(c.G, col.G, a), blend(c.B, col.B, a), blend(c.A, 255, a)})
}

func inRoundRect(x, y, s, r float64) bool {
	cx := math.Min(math.Max(x, r), s-r)
	cy := math.Min(math.Max(y, r), s-r)
	return (x-cx)*(x-cx)+(y-cy)*(y-cy) <= r*r
}

// stroke pinta o segmento com largura w (cobertura por distância ao segmento).
func stroke(img *image.RGBA, x0, y0, x1, y1, w float64, col color.RGBA) {
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
			paint(img, x, y, col, a)
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
