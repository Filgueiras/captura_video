# ADR-0011 — Parear vídeo e áudio pelo aparelho físico

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

A placa de captura aparece no sistema como **dois dispositivos independentes**
([0004](0004-video-e-audio-em-containers-separados.md)): uma entrada de vídeo e
uma de áudio. Nada na lista diz que eles são o mesmo aparelho.

O erro que isso produz é silencioso e caro: o usuário escolhe a placa no combo
de vídeo, deixa o áudio no padrão do sistema — que é o microfone do notebook — e
grava uma hora de material com o som do ambiente em vez do som do HDMI. Só se
descobre ao reproduzir.

Casar por semelhança de nome não funciona de forma confiável. Os nomes são
coisas como `"Interface de áudio digital (2- USB Digital Audio)"` e
`"USB Video"`, e num PC com webcam, headset e placa-mãe com áudio digital há
vários candidatos plausíveis.

## Decisão

Descobrir o par consultando o **sistema operacional sobre a topologia do
hardware**, e não os nomes.

**Windows** — pelo `ContainerId`, o identificador que o Windows atribui ao
aparelho físico. Todas as interfaces do mesmo dongle (vídeo, áudio, HID)
compartilham o mesmo valor. Um script PowerShell lê `DEVPKEY_Device_ContainerId`
das classes `Camera`, `Image` e `AudioEndpoint`, e o pareamento é feito por
igualdade de container.

**Linux** — pela topologia do `sysfs`. O nó de vídeo aponta para a interface USB
(`1-4:1.0`); subindo um nível chega-se ao aparelho (`1-4`), e as outras
interfaces dele estão lado a lado — inclusive a de áudio, que registra um
`sound/cardN`. Desse índice de placa ALSA chega-se ao nome da fonte no
PulseAudio via `pactl`, ou a `hw:N,0` no caminho ALSA puro.

Na interface, a caixa **"Áudio da placa"** (marcada por padrão) aplica o
resultado; desmarcá-la libera a escolha manual.

## Consequências

- O caso comum — plugar a placa e gravar — funciona sem configuração e sem a
  armadilha do microfone errado.
- O pareamento é **por hardware**, não por heurística: não confunde a placa com o
  áudio digital da placa-mãe, mesmo com nomes parecidos.
- No Windows a consulta ao PowerShell leva vários segundos. Por isso ela é
  separada da enumeração e roda depois, em segundo plano
  ([0014](0014-trabalho-demorado-em-qthread.md)).
- Dois códigos de pareamento completamente diferentes para manter, ambos
  isolados em [`dispositivos.py`](../../capturador/dispositivos.py)
  ([0003](0003-fronteira-de-plataforma-em-dispositivos.md)).
- `parear()` **nunca levanta exceção**: sem pareamento a aplicação continua
  inteiramente utilizável, só perde a seleção automática. É um recurso de
  conveniência e falha como tal.
- Sobra uma heurística de nome (`_parece_captura`), usada **apenas** quando o
  pareamento por hardware não achou nada. É um palpite assumido como palpite, e
  não o mecanismo principal.
- O container nulo (`{00000000-...-FFFFFFFFFFFF}`) é explicitamente ignorado: o
  Windows joga nele tudo que não pertence a um aparelho identificável, e agrupar
  por ele juntaria placa-mãe, GPU e webcam num "mesmo aparelho".

## Alternativas consideradas

**Casar por semelhança de nome.** Frágil pelos motivos acima; sobreviveu apenas
como último recurso.

**Deixar o usuário escolher sempre.** É o que o OBS faz, e é onde a gravação com
o microfone errado acontece.

**Assumir que o áudio de captura é o que tem "digital" ou "USB" no nome.** Falha
em qualquer PC com áudio digital integrado — a maioria.
