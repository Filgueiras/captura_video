# ADR-0009 — Medir o que a placa e a máquina entregam

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Duas informações são necessárias para escolher um modo de captura, e **nenhuma
das duas é obtível perguntando**:

1. **A taxa que a placa entrega de fato.** A anunciada mente
   ([0008](0008-descartar-quadros-de-enchimento.md)). Uma placa que diz
   "1920x1080 60 fps" pode entregar 30, ou pode entregar 60 em 720p e 25 em
   1080p.
2. **Se esta máquina acompanha.** Decodificar MJPEG 1080p60 e reduzir para a
   tela é trabalho real. Se esse trabalho não couber no intervalo entre quadros,
   a prévia engasga — e isso depende do computador, não da placa.

Um programa que só lista o que o dispositivo declara empurra a descoberta para o
usuário, por tentativa e erro, sem instrumento para medir.

## Decisão

**Testar equipamento**: abrir cada modo por alguns segundos e medir as duas
coisas de uma vez (`medir_modo()` em [`captura.py`](../../capturador/captura.py)).

Por modo, mede-se:

- `quadros_reais` / `quadros_vazios` — quantos pacotes traziam imagem;
- `ms_por_quadro` — o tempo que **esta máquina** gasta fazendo exatamente o
  trabalho da prévia: decodificar e reduzir à largura da janela;
- `uso` — a fração do intervalo entre quadros consumida por esse trabalho.

De `uso` sai um **veredito**, que é o que o usuário lê:

| `uso` | Veredito | Significado |
|---|---|---|
| < 60% | **Fluido** | folga confortável |
| 60–90% | **No limite** | funciona, sem margem |
| ≥ 90% | **Vai engasgar** | a prévia não acompanha |
| — | **Não abriu** | o modo falhou ao abrir |

O veredito colore a lista de modos e aparece por extenso no relatório final.

Detalhes que a medição exige para não mentir:

- O **primeiro pacote é ignorado**: a latência de abrir o dispositivo (que pode
  ser de segundos) não pertence à conta da taxa de quadros.
- Entre um modo e outro há uma **pausa de 500 ms**, e um modo que falha é
  **tentado de novo** após 1 s. A placa leva um instante para ser liberada
  depois do fechamento; reabrir na hora devolve "I/O error" de vez em quando, e
  sem o retry o teste reportaria falha de um modo perfeitamente bom.
- A medição usa a **largura real da janela de prévia**, não um valor fixo:
  reduzir para 1280 px e reduzir para 640 px custam coisas diferentes.

Também disponível sem abrir a janela: `python -m capturador --medir`.

## Consequências

- O usuário descobre em ~30 segundos o que descobriria em meia hora de tentativa
  e erro — ou nunca, porque não saberia que havia o que descobrir.
- O número exibido durante a captura é o real, não o anunciado.
- O teste **interrompe a prévia**: a placa aceita um cliente por vez. Por isso é
  uma ação explícita, com estimativa de duração e confirmação, e não algo que
  aconteça sozinho na inicialização.
- Custa tempo proporcional ao número de modos. Só os modos comprimidos são
  testados por padrão (os crus são inviáveis por banda USB de qualquer forma);
  `--tudo` inclui os demais.
- Vereditos são um julgamento com limiares arbitrários (60% e 90%). São palpites
  calibrados, não física — mas um palpite explícito e consistente é melhor que
  entregar `ms_por_quadro` cru para o usuário interpretar.

## Alternativas consideradas

**Confiar no que o dispositivo anuncia.** É o que os players fazem, e é o motivo
de eles entregarem imagem ruim.

**Medir sozinho, na inicialização.** Trinta segundos de janela travada toda vez
que o programa abre, para um dado que quase nunca muda.

**Uma tabela de placas conhecidas.** Impossível de manter e não cobre a metade
que depende da máquina do usuário.
