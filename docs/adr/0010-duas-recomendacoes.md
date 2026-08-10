# ADR-0010 — Apresentar duas recomendações em vez de uma "melhor"

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Terminado o teste de equipamento ([0009](0009-medir-em-vez-de-confiar.md)), há
uma tabela de modos com taxa real e custo de CPU. O impulso natural é ordenar
por alguma pontuação e apontar o vencedor.

Não existe vencedor. Mais quadros por segundo e mais pixels por quadro competem
pelo **mesmo orçamento** — a banda do USB e a capacidade da máquina. Placas
costumam ter um degrau nítido onde subir a resolução derruba a taxa pela metade.
E qual lado do degrau é o certo depende inteiramente do que se está gravando:

- capturar um **jogo ou vídeo** → movimento importa, 720p60 ganha de 1080p30;
- capturar **slides, planilha ou código** → texto legível importa, 1080p30 ganha.

Uma pontuação única precisaria escolher um peso entre as duas coisas, e esse
peso é uma propriedade do usuário, não do hardware.

## Decisão

Apresentar **duas** recomendações, nomeadas pelo caso de uso, com um botão para
cada uma (`_recomendacoes()` em [`janela.py`](../../capturador/janela.py)):

- **Movimento** (jogos, vídeo) — maximiza a taxa; entre modos de taxa
  equivalente, o de maior resolução.
- **Detalhe** (slides, texto) — maximiza a resolução; entre modos de resolução
  equivalente, o de maior taxa.

Só entram modos com veredito *Fluido* ou *No limite*. Quando os dois critérios
apontam para o mesmo modo, a interface diz isso — *"Um modo se destaca"* — e
mostra um botão só.

O detalhe que faz a coisa funcionar é o **agrupamento em faixas de 5 fps**:

```python
def faixa(medicao):
    return round(medicao.fps_real / 5) * 5
```

Sem isso, 59,85 fps "ganharia" de 59,70 fps e o ruído da medição escolheria a
resolução do usuário. Arredondando em degraus de 5, "praticamente a mesma taxa"
vira um empate, e quem desempata passa a ser a resolução — que é o que a pessoa
percebe olhando.

## Consequências

- A escolha é apresentada como o que ela é: um par de opções com uma pergunta
  clara ("o que você vai gravar?"), em vez de um número mágico.
- O usuário aprende o trade-off do próprio hardware ao ver as duas pontas.
- Duas recomendações são mais texto para ler que uma. Mitigado por rotular pelo
  **uso** e não pelas especificações: "Movimento (jogos, vídeo)" responde à
  pergunta sem exigir interpretar "1280x720 60 fps".
- O teste continua listando todos os modos medidos: as recomendações são um
  atalho, não uma restrição.

## Alternativas consideradas

**Uma pontuação única (por exemplo `pixels × fps`).** Simples e errada:
1080p30 e 720p60 empatam nessa conta e são experiências completamente
diferentes. Onde não empatam, o vencedor sai de um peso arbitrário.

**Perguntar antes o que o usuário vai gravar e recomendar um só.** Uma tela a
mais antes do resultado, e transfere a decisão para um momento em que ele ainda
não viu os números.

**Só mostrar a tabela.** Foi o comportamento inicial. Informação demais, decisão
de menos — a tabela responde "quanto" mas não "e daí".
