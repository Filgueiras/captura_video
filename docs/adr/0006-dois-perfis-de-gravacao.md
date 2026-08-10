# ADR-0006 — Dois perfis: Original (remux, MKV) e H.264 (MP4)

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Uma placa de captura já entrega vídeo **comprimido** (MJPEG, às vezes H.264): é
o que cabe no barramento USB. Um programa de gravação tem então duas opções para
cada pacote que chega:

1. **Decodificar e recodificar** — o caminho que todo mundo espera, e que
   introduz uma perda de geração e consome CPU ou GPU.
2. **Copiar os bytes para o arquivo de saída** sem tocar neles (*remux*) — a
   qualidade fica **idêntica** à do hardware e a CPU fica perto de zero.

Recodificar MJPEG 1080p60 em H.264 na CPU é trabalho real e concorre com a
prévia. E a perda é gratuita: a placa já comprimiu uma vez.

Mas o remux não serve para tudo. Ecrã e janela chegam **crus** (BGRA): 1080p60 em
BGRA são ~500 MB/s. "Copiar sem perda" ali significa encher o disco em segundos.

## Decisão

Dois perfis, escolhidos pelo usuário:

| | **Original** | **H.264** |
|---|---|---|
| Container | `.mkv` | `.mp4` |
| Vídeo | remux, cópia direta | recodificado |
| Áudio | remux (PCM) | AAC 192 kbit/s |
| Qualidade | idêntica ao hardware | ajustável (CRF/CQ) |
| CPU/GPU | quase nada | moderado |
| Tamanho | ~150 MB/min a 1080p30 | bem menor |
| Fontes | só placa de captura | placa, ecrã e janela |

O perfil Original fica **desabilitado** quando a fonte é ecrã ou janela, pelo
motivo acima. A propriedade `DispositivoVideo.permite_copia` é o que decide, e a
interface reflete isso desabilitando o item do combo com um tooltip explicando —
em vez de deixar escolher e falhar depois.

## Consequências

- Quem quer arquivar ou editar depois grava sem nenhuma perda de geração, com a
  máquina praticamente parada.
- Quem quer compartilhar tem arquivo pequeno, com aceleração de GPU quando
  disponível ([0013](0013-so-codificadores-que-abrem.md)).
- **MKV para o perfil Original**, e não MP4, por dois motivos independentes:
  - MP4 não aceita legalmente MJPEG com áudio PCM; MKV aceita qualquer
    combinação de codecs.
  - MKV sobrevive a um desligamento no meio da gravação — o arquivo continua
    abrindo, com o que já tinha sido escrito. Um MP4 interrompido perde o índice
    e vira lixo. Numa captura ao vivo, que por definição pode ser interrompida
    por qualquer coisa, isso importa.
- No perfil Original, o pacote precisa ser **decodificado antes de ser gravado**,
  nunca depois: o `mux` se apropria do buffer do pacote e o esvazia. Decodificar
  em seguida devolveria nada e a prévia ficaria preta durante a gravação — bug
  real, encontrado e agora comentado no laço de captura.
- Dois caminhos de gravação para manter, cada um com seu tratamento de erro.
- Preset `veryfast` + `zerolatency` no libx264: numa captura ao vivo, perder
  quadro é pior que gerar arquivo maior. Não é o padrão do x264 e é intencional.

## Alternativas consideradas

**Só recodificar, sempre.** Um caminho de código, previsível, um formato de saída
único. Descartado: joga fora o principal argumento técnico do programa, que é
gravar exatamente o que o hardware produziu.

**Só remultiplexar, sempre.** Impossível para ecrã e janela, e deixaria quem só
quer um arquivo pequeno para mandar por mensagem sem saída.

**MKV nos dois perfis.** Mais consistente internamente, pior na vida real: MP4 é
o que abre sem pensar em celular, editor e navegador — que é justamente o destino
de quem escolheu H.264.
