# ADR-0012 — Ecrã pelo `ddagrab`, janela pelo `gdigrab`

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Depois da placa de captura, os dois pedidos naturais são "grave a minha tela" e
"grave só esta aplicação". No Windows há dois caminhos possíveis, e a diferença
entre eles não é sutil:

| Método | O que é | Medido nesta máquina |
|---|---|---|
| `gdigrab` | GDI clássico, copia o framebuffer pela CPU | **17 fps** (1920x1080) |
| `ddagrab` | Desktop Duplication API, na GPU — a mesma via do OBS | **41 fps** (1920x1080) |

Só que o `ddagrab` **não sabe capturar uma janela específica**: ele duplica uma
saída de vídeo inteira. Para uma aplicação isolada, `gdigrab` é o único caminho —
e ali ele se sai bem, entregando 30 fps sem esforço, porque a área é menor.

O `ddagrab` também não entra como dispositivo: é um **filtro do `lavfi`**, então
a configuração inteira mora dentro de uma string de filtro, e não em opções.

## Decisão

Escolher o método pelo **tipo de fonte**, dentro de `DispositivoVideo.entrada()`:

- **Ecrã, Windows** → `ddagrab` via `lavfi`, quando disponível; queda para
  `gdigrab` se o `lavfi` não estiver no PyAV instalado.
- **Janela, Windows** → `gdigrab` com `title=<título da janela>`.
- **Todos os ecrãs juntos, Windows** → `gdigrab`, obrigatoriamente: o `ddagrab`
  duplica uma saída de cada vez.
- **Linux** → `x11grab` para ambos. Sob Wayland puro, a lista de ecrãs volta
  **vazia** de propósito: o `x11grab` não enxerga a tela e ofereceria uma opção
  que só produz preto.

## Consequências

- Captura de ecrã no Windows em 41 fps em vez de 17 — a diferença entre usável e
  não usável.
- Capturar os dois monitores num arquivo só é possível, e custa o dobro de
  pixels: o desktop combinado (3840x1080) caiu para **11 fps** aqui. A opção
  existe, com o nome dizendo o tamanho, para a escolha ser informada.
- **A ordem dos monitores é a do DXGI, não a das coordenadas.** Isto é uma
  armadilha verificada nesta máquina: `output_idx=0` é o monitor **principal**,
  mesmo estando fisicamente à direita do outro. Ordenar a lista por posição
  horizontal — que parece a coisa natural a fazer — faria o usuário escolher um
  ecrã e gravar o outro. Por isso `_telas_windows()` ordena por
  `(não é principal, x, y)`, e o comentário no código avisa.
- `SetProcessDPIAware()` é chamado antes de medir os monitores. Sem isso o
  Windows mente sobre as dimensões em telas com escala diferente de 100%, e a
  captura sai cortada ou esticada.
- Ecrã e janela chegam **crus** (BGRA), o que torna o perfil Original inviável
  para elas — ver [0006](0006-dois-perfis-de-gravacao.md).
- Nada disso vaza para fora de
  [`dispositivos.py`](../../capturador/dispositivos.py): o motor de captura
  recebe `(caminho, formato, opções)` e não sabe qual método foi escolhido
  ([0003](0003-fronteira-de-plataforma-em-dispositivos.md)).

## Alternativas consideradas

**Só `gdigrab`, para os dois casos.** Um caminho de código, 17 fps de captura de
ecrã. Rejeitado pelo número.

**Windows.Graphics.Capture (a API moderna, que captura janelas na GPU).**
Resolveria janela *e* ecrã com desempenho de GPU. Exige WinRT, o que traz uma
dependência nativa considerável e não tem equivalente no Linux — dois motivos
para não pagar por um recurso secundário.

**PipeWire para captura de tela no Linux (o caminho do Wayland).** É a resposta
certa para Wayland e ficou de fora por ora; hoje o programa admite que não sabe
e não oferece a opção, em vez de oferecer uma tela preta.
