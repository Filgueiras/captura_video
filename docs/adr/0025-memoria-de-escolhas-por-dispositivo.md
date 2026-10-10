# ADR-0025 — Memória de escolhas e medições, por dispositivo, em SQLite

**Estado:** Aceito
**Data:** 2026-09-18

Revê parcialmente o [0017](0017-preferencias-em-qsettings.md), que decidiu **não**
persistir dispositivo nem modo.

## Contexto

O relato do usuário foi: *"a opção que eu costumo usar sai da lista; ela só volta
a aparecer quando eu mando testar a placa"*. Investigando, eram **dois** defeitos
distintos que se disfarçavam de um só, os dois em torno do número 30.

**1. O modo de 30 fps era apagado da lista.** `_dedup_modos` guardava, por
codec+resolução, apenas a maior taxa. O MS2109 oferece 1920x1080 a 60, 30, 25, 20
e 10 fps; só o 60 chegava ao combo. A intenção era enxugar uma lista de cinquenta
itens, e isso continua válido — mas o 30 fps não é sobra, é escolha.

Medido aqui, pedindo cada um dos dois à mesma placa, com sinal HDMI presente:

| Pedido | Quadros úteis | Quadros de enchimento |
|---|---|---|
| 60 fps | 30,2/s | 30,0/s (**50% de lixo**) |
| 30 fps | 30,2/s | 0/s |

Pedir 60 **não entrega um quadro útil a mais**: entrega o dobro de tráfego USB e
metade de lixo, que o programa depois descarta
([0008](0008-descartar-quadros-de-enchimento.md)). Pedir 30 é estritamente melhor
nesta placa, e era justamente a opção indisponível.

**2. Depois do teste, os dois modos ficavam com o mesmo rótulo.** `_pintar_modos`
substituía a taxa pedida pela medida, então 1080p60 virava
`1920x1080  30 fps reais` — idêntico ao 1080p30. É daí que vinha a sensação de
que "o 30 volta quando eu testo": não voltava, o 60 é que passava a se chamar 30.

**3. Nada disso sobrevivia ao fechamento.** As medições viviam num `dict` em
memória, e o [0017](0017-preferencias-em-qsettings.md) deliberadamente não
persistia o modo. Quem usa sempre a mesma placa refazia a escolha — e o teste de
~30 s — a cada abertura.

O motivo do 0017 para não persistir continua correto: *"restaurar uma placa que
não está mais conectada geraria um erro na abertura em vez de conveniência"*. O
que ele não previu foi restaurar **dentro** do que a enumeração encontrou agora.

## Decisão

**Parar de apagar modos**: `_dedup_modos` guarda a maior taxa oferecida *e* as
taxas de `TAXAS_TELA` (60, 30, 24, 15). Aqui a lista vai de 22 para 33 itens, e
1920x1080 passa a ter 60 e 30.

**Mostrar a taxa pedida junto da medida** quando as duas divergem:
`● 1920x1080  60 → 30 fps reais  [mjpeg]`. Quando coincidem, o número aparece uma
vez só. A seta é a informação que faz a escolha entre os dois modos deixar de ser
adivinhação.

**Guardar por dispositivo, em SQLite**, num módulo novo
([`memoria.py`](../../capturador/memoria.py)): o modo escolhido, o perfil, o fator
de qualidade e o resultado completo de «Testar equipamento», modo a modo. O banco
fica em `~/.local/share/capturador/memoria.sqlite3` (ou `%LOCALAPPDATA%` no
Windows) — nunca ao lado do executável, que em `Program Files` não é gravável
([0018](0018-empacotar-com-pyinstaller-em-modo-pasta.md)).

A chave é `{tipo}:{identidade}`, e a identidade é escolhida para **sobreviver a um
reinício**, o que `caminho` não faz: `/dev/video0` vira `/dev/video1` conforme a
ordem de conexão, e o identificador de uma janela X muda a cada execução do
aplicativo. Então: nome do aparelho para placas, índice da saída para ecrãs,
título para janelas.

Três regras de segurança, porque memória errada é pior que memória nenhuma:

- **O modo lembrado só é reaplicado se o aparelho ainda o oferecer.** É o que
  concilia esta decisão com o 0017: a restauração acontece contra a lista real
  daquele momento, então uma entrada HDMI que mudou de resolução simplesmente cai
  no palpite automático, sem erro.
- **Preencher a interface não grava nada** (a trava `_restaurando`). Sem isso, o
  próprio ato de abrir a janela sobrescreveria a memória com o palpite automático
  — que é exatamente o que ela existe para não fazer.
- **Medição vence em 180 dias.** Ela mede *esta máquina*, e máquina muda.

`QSettings` continua com as dez preferências globais do
[0017](0017-preferencias-em-qsettings.md); elas seguem sendo o padrão para um
aparelho nunca visto. SQLite entra só onde o dado é estruturado e multiplicado
por dispositivo — dezenas de medições com sete campos cada.

## Consequências

- **O 30 fps existe, é escolhível e é lembrado.** Verificado ponta a ponta:
  escolher 1080p30, fechar e reabrir devolve 1080p30 selecionado.
- **«Testar equipamento» virou investimento, não pedágio.** Os vereditos e as
  cores voltam na abertura seguinte sem medir de novo.
- **Perfil e qualidade passam a ser por dispositivo.** Arquivar de uma placa e
  compartilhar uma captura de tela pedem ajustes diferentes, e antes um
  sobrescrevia o outro.
- A lista de modos ficou 50% mais longa. É o preço de não esconder escolhas
  legítimas, e o rótulo com a seta ajuda a navegar.
- **Duas fontes de verdade para preferências** — `QSettings` e SQLite. É a
  consequência ruim de verdade desta decisão. Mitigada pela fronteira ser
  explícita: global e simples no `QSettings`, por dispositivo e estruturado no
  SQLite; e `memoria.py` não importa Qt, então a separação não é só convenção.
- Um arquivo novo a gerenciar, que o usuário nunca pediu para gerenciar. Daí o
  `--memoria` (mostra tudo, com o caminho do banco) e o `--esquecer`.
- Toda função de `memoria.py` engole as próprias exceções. Banco corrompido,
  disco cheio ou pasta somente-leitura custam a memória, nunca a captura.

## Alternativas consideradas

**Só corrigir o `_dedup_modos` e não guardar nada.** Resolveria a queixa literal
— o modo sumido —, e foi a primeira coisa feita. Mas deixaria de pé o teste de
30 s refeito a cada abertura, que era metade do incômodo.

**JSON ou mais chaves no `QSettings`.** O 0017 já rejeitou JSON ao lado do
executável, e por um motivo que continua valendo. `QSettings` aguentaria a
escolha por dispositivo, mas não as medições: são dezenas de registros com sete
campos, e representá-los em chaves planas seria inventar um banco pior. SQLite é
da biblioteca padrão, não acrescenta dependência
([0002](0002-ffmpeg-embutido-via-pyav.md)) e sobrevive a um desligamento no meio
da escrita.

**Guardar também o veredito e o `fps_real`.** Descartada: são propriedades
derivadas dos contadores. Guardá-las seria manter a mesma verdade em dois lugares
para elas divergirem depois — o cálculo é o mesmo na leitura.

**Reaplicar o modo lembrado mesmo que a placa não o ofereça mais.** Seria
"respeitar a escolha do usuário" ao pé da letra, e produziria exatamente o erro
de abertura que o [0017](0017-preferencias-em-qsettings.md) queria evitar.
