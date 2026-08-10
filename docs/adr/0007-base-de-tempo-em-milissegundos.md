# ADR-0007 — Base de tempo em milissegundos, no fluxo **e** no codec

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Este ADR registra um bug intermitente que custou caro e cuja correção parece
redundante — exatamente o tipo de linha que alguém "limpa" depois sem saber.

No perfil H.264, os quadros recebem carimbos de tempo em segundos
([0005](0005-sincronia-por-ancora-de-relogio.md)) e o libavcodec os converte para
a base de tempo do codec. Se a base de tempo do **contexto do codec** não for
definida explicitamente, o libavcodec a deriva do parâmetro `rate` do fluxo:
para 30 fps, `1/30`.

Numa base de 1/30, dois quadros que chegaram a 33 ms e a 66 ms viram,
respectivamente, PTS 1 e PTS 1 — **o mesmo valor**, porque a placa não entrega
exatamente a cada 33,33 ms e o arredondamento colapsa os dois no mesmo tique.

E aí os dois containers se comportam de forma diferente:

- **Matroska** tolera PTS repetido e grava.
- **MP4** recusa com `EINVAL` e a gravação morre.

Como o perfil H.264 grava em MP4 ([0006](0006-dois-perfis-de-gravacao.md)), o
resultado era uma falha que aparecia ou não dependendo de onde, no tempo, os
quadros caíam. Ou seja: reproduzia em algumas gravações e em outras não, sem
padrão visível.

## Decisão

Fixar a base de tempo em **milissegundos** (`Fraction(1, 1000)`) nos **dois**
lugares, em `_criar_codificador_video()`:

```python
fluxo.time_base = Fraction(1, 1000)
fluxo.codec_context.time_base = Fraction(1, 1000)
```

Definir só no fluxo **não basta** — é essa a parte contraintuitiva. O
`codec_context` tem a sua própria base de tempo e é ela que governa a conversão
do PTS na codificação.

## Consequências

- Resolução de 1 ms para os carimbos: mais que suficiente para 240 fps
  (4,2 ms entre quadros) e sem colisão de arredondamento em taxa nenhuma.
- A gravação em MP4 deixou de falhar de forma intermitente.
- A linha duplicada **parece** redundante e não é. O comentário no código diz
  isso; este ADR é o registro completo, para quem for tentado a simplificar.
- Alinha com a base usada na codificação de áudio e na conversão de âncora, que
  já trabalham em milissegundos.

## Alternativas consideradas

**Base de 1/90000 (a convenção de MPEG-TS).** Funcionaria igualmente bem e é o
padrão em transporte de streams. Milissegundos foram preferidos por serem
legíveis num depurador sem fazer conta de cabeça.

**Forçar carimbos monotonicamente crescentes com um contador de quadros.**
Eliminaria a colisão, mas descartaria o espaçamento real entre quadros, que é
justamente o que o [0005](0005-sincronia-por-ancora-de-relogio.md) existe para
preservar.

**Gravar o perfil H.264 em MKV também.** Contornaria o sintoma escondendo o
defeito — o arquivo continuaria com PTS repetido, só que num container que não
reclama.
