# ADR-0019 — Português no código, nos comentários e na interface

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

A convenção dominante em software é escrever código em inglês, mesmo quando
ninguém na equipe fala inglês no dia a dia. Este projeto tem um público
específico — usuários e mantenedores lusófonos — e um objetivo declarado de ser
**explicável**: metade do valor está nos comentários que dizem por que uma linha
existe, e nas mensagens de erro que dizem o que fazer.

## Decisão

**Português em tudo o que é nosso**: nomes de módulos, classes, funções,
variáveis, comentários, docstrings, textos da interface e mensagens de erro.

Fica em inglês, sem tradução, o que **não é nosso**:

- API do Qt e do PyAV (`paintEvent`, `setValue`, `demux`, `time_base`);
- opções e nomes de formato do FFmpeg (`rtbufsize`, `input_format`, `ddagrab`);
- termos técnicos sem tradução estabelecida ou cuja tradução atrapalharia a
  busca por documentação (`mux`, `codec`, `container`, `pts`).

Convenções: sem acento em identificadores (`descricao`, não `descrição`), com
acento em comentários e strings de interface.

## Consequências

- Os comentários — que são densos neste projeto, e propositalmente — se leem na
  língua em que quem os mantém pensa. `# A placa leva um instante para ser
  liberada depois do fechamento` explica melhor que a versão traduzida por
  alguém que não fala inglês nativamente.
- As mensagens de erro chegam ao usuário na língua dele, já acionáveis: *"A placa
  aceita um programa por vez. Feche o VLC, o OBS..."*.
- Não existe camada de tradução (i18n) nem arquivo de strings: o texto está onde
  é usado. Internacionalizar depois custaria caro — e não está previsto.
- Ler o código exige ler português. Para um colaborador que não fale a língua,
  isso é uma barreira real.
- A mistura é inevitável e às vezes feia: `def paintEvent(self, evento)` tem
  nome em inglês e parâmetro em português, porque o nome é imposto pelo Qt. O
  `# noqa: N802` ao lado marca essas fronteiras.
- Grafia mista de português europeu e brasileiro ("ecrã" ao lado de "arquivo") —
  intencional: usa-se o termo mais claro para o usuário em cada caso.

## Alternativas consideradas

**Código em inglês, interface em português.** A convenção padrão da indústria, e
o que se faria num projeto com colaboradores de vários países. Rejeitado porque
criaria uma tradução constante entre o vocabulário do domínio ("placa de
captura", "quadro vazio", "veredito") e os identificadores — e porque os
comentários, que aqui carregam o raciocínio, ficariam empobrecidos.

**Tudo em inglês.** Coerente, e entrega mensagens de erro que o usuário-alvo não
lê no momento em que mais precisa entender.
