# ADR-0008 — Descartar os quadros de enchimento que a placa emite

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Muitas placas HDMI→USB baratas anunciam uma taxa de quadros que o hardware não
sustenta. O chip **MS2109**, um dos mais comuns, declara 60 fps e entrega 30:
alterna um quadro real com um **quadro JPEG vazio de 4 bytes** — só os
marcadores `SOI` + `EOI`, sem imagem nenhuma dentro.

Isso é feito para manter a cadência declarada no descritor USB. O efeito
colateral é grave:

- Esses pacotes **não decodificam**. Cada um deles vira um erro no decodificador.
- Numa gravação por cópia direta ([0006](0006-dois-perfis-de-gravacao.md)), eles
  vão para o arquivo. Metade dos quadros do arquivo fica corrompida.
- Os players que mostram "60 fps" estão contando esses quadros. O número está
  tecnicamente correto e é enganoso.

## Decisão

Em fluxos MJPEG, descartar todo pacote menor que **256 bytes**
(`_MIN_BYTES_JPEG` em [`captura.py`](../../capturador/captura.py)) antes de
qualquer outro processamento — decodificação, gravação ou contagem.

O corte funciona porque a separação entre os dois casos é enorme, não apertada:
um quadro de enchimento tem 4 bytes; um quadro JPEG com imagem real, mesmo
minúsculo e completamente preto, tem alguns kilobytes. Não existe nada no meio.

## Consequências

- Arquivos gravados por cópia direta ficam íntegros, sem quadros corrompidos.
- O contador de fps mostra a taxa **real**, que é a que o usuário percebe. Um
  número menor que o do VLC — e certo.
- A medição separa as duas contagens (`quadros_reais` e `quadros_vazios`), o que
  permite ao teste de equipamento ([0009](0009-medir-em-vez-de-confiar.md))
  informar *"60 anunciados, 30 reais"* em vez de só mostrar 30 e deixar o
  usuário achando que o programa está lento.
- Quadros de enchimento **não contam como perdidos** nas estatísticas: nunca
  houve imagem para perder. Contá-los como perda produziria um alarme falso
  permanente.
- O filtro é aplicado só a MJPEG. Placas H.264 não usam esse truque, e um pacote
  H.264 pequeno pode ser um quadro-P legítimo — descartá-lo quebraria o fluxo.
- Se aparecer uma placa que use enchimento com pacotes maiores que 256 bytes, o
  limiar precisa ser revisto. Nenhuma encontrada até agora.

## Alternativas consideradas

**Tentar decodificar e descartar o que falhar.** Correto em teoria, caro na
prática: paga-se uma chamada de decodificação e um erro por metade dos pacotes,
e não resolve o perfil Original, onde a gravação por cópia nem decodifica.

**Detectar pelos bytes do JPEG (procurar por dados após o `SOI`).** Mais preciso
e mais frágil: exige interpretar a estrutura do JPEG a cada pacote para
distinguir dois casos que já estão separados por três ordens de grandeza no
tamanho.

**Não filtrar e avisar o usuário.** Foi a primeira tentativa. Produz arquivos
inutilizáveis com um aviso ao lado — o usuário fica sabendo que o vídeo está
quebrado, o que não é a mesma coisa que ter um vídeo.
