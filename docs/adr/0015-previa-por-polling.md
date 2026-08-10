# ADR-0015 — Prévia por polling, com o quadro já reduzido na thread de captura

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

A thread de captura produz quadros a 30–60 por segundo; a interface precisa
desenhá-los. Entre as duas há duas perguntas independentes:

1. **Quem manda o quadro para a tela?** A thread empurra (sinal por quadro) ou a
   interface busca (polling)?
2. **Onde o quadro é reduzido ao tamanho da janela?** Um quadro 1080p tem 6 MB em
   RGB; a área de prévia costuma ter menos de um terço disso em pixels.

Empurrar por sinal a 60 fps enfileira 60 eventos por segundo no laço do Qt. Se a
interface atrasar por qualquer motivo, a fila cresce e passa-se a desenhar
quadros velhos — o pior resultado possível, porque o atraso vira permanente.

## Decisão

**Polling com número de série.** O motor guarda um único quadro (o mais recente)
protegido por lock, com um contador que incrementa a cada troca. Um `QTimer` de
8 ms pergunta:

```python
quadro, serie = self.motor.obter_quadro(self._serie_quadro)
if quadro is not None:      # None = nada novo desde a última vez
    self.tela.definir_quadro(quadro)
```

Se a placa produziu três quadros entre dois ticks, **dois são simplesmente
descartados** — o que está na tela é sempre o mais recente que existe.

**A redução acontece na thread de captura**, não na de desenho: `reformat()` já
converte para a largura útil da janela, informada por
`definir_largura_preview()` e reatualizada no `resizeEvent`. A conversão vai
direto de MJPEG para RGB no tamanho final, numa passagem de `swscale`.

Três timers, com períodos diferentes porque as necessidades são diferentes:

| Timer | Período | Para quê |
|---|---|---|
| vídeo | 8 ms | acompanhar até 120 fps sem atrasar |
| áudio | 10 ms | alimentar o `QAudioSink` antes de ele esvaziar |
| estado | 300 ms | fps, tamanho do arquivo, medidor — mudanças que o olho não acompanha mais rápido |

## Consequências

- Impossível acumular atraso: sem fila, não há o que atrasar.
- O trabalho pesado (decodificar + reduzir) fica fora da thread da interface, na
  thread que já solta o GIL enquanto espera o dispositivo.
- Reduzir na origem economiza escalar 1080p a cada quadro no desenho — a
  diferença entre uma prévia fluida e uma que engasga em janela pequena.
- É o mesmo trabalho que o teste de equipamento cronometra
  ([0009](0009-medir-em-vez-de-confiar.md)), o que faz a medição prever o
  comportamento real em vez de um número de laboratório.
- Timers gastam CPU mesmo parados. A 8 ms, o custo de um tick que não faz nada é
  desprezível.
- O `QImage` **não copia** os bytes do array: o `numpy.ndarray` precisa continuar
  vivo enquanto a imagem existir. Por isso `TelaVideo` guarda o buffer num
  atributo — soltá-lo produziria lixo na tela ou uma falha de segmentação.
- A foto em resolução nativa não pode sair da prévia (que está reduzida), então
  é pedida sob demanda: `solicitar_quadro_cheio()` levanta uma flag e o próximo
  quadro é convertido também em tamanho original.

## Alternativas consideradas

**Sinal do Qt por quadro.** Simples e correto no papel; enfileira sob carga e
transforma um atraso momentâneo em atraso permanente.

**Fila com tamanho máximo entre as threads.** Resolve o acúmulo, e uma fila de
tamanho 1 *é* exatamente o que está implementado — só que sem a alocação e sem o
gerenciamento de fila.

**Desenhar com OpenGL / `QOpenGLWidget`.** Mais rápido no desenho, que não é o
gargalo: o custo está em decodificar e reduzir, e ambos já saíram da thread da
interface. Traria dependência de driver de GPU em troca de nada mensurável.
