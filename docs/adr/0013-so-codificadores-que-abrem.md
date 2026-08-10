# ADR-0013 — Oferecer só os codificadores que abrem nesta máquina

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

No perfil H.264 ([0006](0006-dois-perfis-de-gravacao.md)) o usuário escolhe o
codificador. Existem quatro candidatos:

| Codificador | Onde |
|---|---|
| `h264_nvenc` | GPU NVIDIA |
| `h264_qsv` | GPU integrada Intel |
| `h264_amf` | GPU AMD |
| `libx264` | CPU, sempre disponível |

O problema: **estar compilado no FFmpeg não significa funcionar aqui.** O wheel
do PyAV traz os quatro. Numa máquina sem GPU NVIDIA, `h264_nvenc` existe na
lista de codecs e falha no `open()`. Uma GPU antiga ou um driver desatualizado
produzem o mesmo resultado.

Listar os quatro sempre significa que o usuário escolhe NVENC, aperta Gravar e
recebe um erro — possivelmente depois de já ter começado o que queria capturar,
que é justamente o momento em que não dá para repetir.

## Decisão

Na inicialização, **tentar abrir cada codificador de verdade** e listar só os que
abriram (`codificadores_disponiveis()` em
[`janela.py`](../../capturador/janela.py)):

```python
contexto = av.codec.CodecContext.create(nome, "w")
contexto.width, contexto.height = 640, 480
contexto.pix_fmt = "yuv420p"
contexto.time_base = Fraction(1, 30)
contexto.open()      # é aqui que a verdade aparece
contexto.close()
```

`libx264` é a rede de segurança: se nada abrir, ele é oferecido de qualquer
forma, porque um combo vazio é pior que uma opção que provavelmente funciona.

## Consequências

- Não existe opção na interface que falhe na hora de gravar. O que está na lista
  abre.
- O teste é barato — 640x480, abre e fecha sem codificar nada — e roda uma vez,
  na montagem do cartão de gravação.
- Custa uma fração de segundo na abertura do programa, e alguns drivers de GPU
  gastam mais que isso para inicializar. É um preço fixo pago uma vez.
- Se a máquina ganhar uma GPU nova depois, é preciso reabrir o programa para ela
  aparecer. Aceitável: trocar de GPU sem reiniciar não é um cenário.
- O `except Exception` é deliberadamente amplo: drivers de GPU falham de formas
  criativas, e qualquer falha aqui tem a mesma resposta — não ofereça esse
  codificador.

## Alternativas consideradas

**Listar os quatro e tratar o erro na gravação.** É o comportamento padrão da
maioria dos programas e produz exatamente a falha descrita acima, no pior momento
possível.

**Detectar a GPU (por `nvidia-smi`, WMI, `/proc`) e inferir.** Detecta o
hardware, não o driver, que é onde a falha realmente mora. Mais código, mais
específico de plataforma, resposta menos confiável que simplesmente tentar.

**Testar sob demanda, quando o usuário escolhe no combo.** Move a espera para um
lugar onde ela é mais estranha (o combo trava ao selecionar) e não evita a lista
com opções inválidas.
