# How RoBERTa Changes BERT’s Pre-training, and How Much Those Changes Matter on SQuAD and MNLI

## Executive Summary

RoBERTa is best understood not as a new architecture, but as a more aggressively and more carefully trained version of BERT. It keeps BERT’s core masked language modeling idea, but changes several parts of the pre-training recipe: it removes the next sentence prediction (NSP) objective, replaces static masking with dynamic masking, trains on longer contiguous text spans rather than relying on BERT’s original sentence-pair format, uses much larger batches, trains for longer, and uses more pre-training data. In the evidence provided by the RoBERTa paper, these changes matter substantially on both SQuAD and MNLI, but they do not all matter equally. The largest gains come from scale and optimization—more data, larger batches, and longer training—while dynamic masking alone contributes only small gains, and removing NSP becomes helpful when paired with a better input-format design rather than treated in isolation ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf); [Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf)).

My concrete assessment is that RoBERTa’s main contribution is not proving that BERT’s objective was wrong, but proving that BERT’s original pre-training recipe was under-optimized. The numbers on SQuAD and MNLI strongly support that interpretation: RoBERTa achieves large improvements while retaining the masked language model objective, which suggests that training procedure, data scale, and example construction mattered at least as much as objective design in this period of NLP progress ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## BERT’s Original Pre-training Setup

BERT pre-trains a bidirectional Transformer using two tasks: masked language modeling (MLM) and next sentence prediction (NSP). The model is then fine-tuned with minimal task-specific changes for downstream tasks such as SQuAD and MNLI ([Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf)).

In BERT’s original setup, input examples are constructed as sentence pairs, and the model learns whether one segment follows the other through the NSP objective. The BERT paper also argued that removing NSP hurt performance on tasks including MNLI and SQuAD 1.1, which initially made NSP appear important to downstream quality ([Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf)).

This baseline matters because RoBERTa is explicitly a re-evaluation of those design choices. Rather than replacing BERT’s core bidirectional MLM objective with a fundamentally different pre-training target, RoBERTa asks whether BERT was simply not trained optimally enough the first time ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## What RoBERTa Changes in Pre-training

### High-level changes

RoBERTa changes BERT’s pre-training in several important ways:

1. **Removes the NSP objective** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
2. **Uses dynamic masking instead of static masking** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
3. **Changes input construction**, favoring longer contiguous spans such as full sentences or document-level sentences instead of BERT’s original sentence-pair format ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
4. **Trains with much larger batches**—for example, 8K sequences instead of BERT’s 256 in one large-model comparison ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
5. **Pre-trains on more data**, moving from roughly BookCorpus + Wikipedia scale to around 160 GB of text in a key experiment ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
6. **Pre-trains longer**, with results reported from 100K to 500K steps in one major ablation series ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
7. **Trains on longer sequences**, which the paper identifies as another beneficial design change, though the provided excerpts do not include a separate quantitative ablation for sequence length alone ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### BERT vs. RoBERTa at a glance

| Aspect | BERT | RoBERTa |
|---|---|---|
| Core objective | MLM + NSP | MLM only; NSP removed |
| Masking | Static masking | Dynamic masking |
| Input format | Sentence-pair format | Full/document-level contiguous text formats explored |
| Batch size in cited large-model comparison | 256 | 8K |
| Pre-training data in cited comparison | ~13 GB BookCorpus + Wikipedia | Up to ~160 GB |
| Training duration in cited comparison | 1M steps for BERT Large baseline in cited table | 100K–500K steps in cited RoBERTa scaling table |
| Goal | Original bidirectional pre-training recipe | Robustly optimized BERT pre-training |

*Note. Compiled from* [Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf) *and* [Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf).

## How Much the Changes Matter: Evidence on SQuAD and MNLI

## 1. Dynamic Masking: Helpful, but Not the Main Story

RoBERTa directly compares static and dynamic masking in a BERTBASE-style setting. On SQuAD 2.0, the reported F1 goes from **78.3** with static masking to **78.7** with dynamic masking. On MNLI-m, performance moves from **84.3** to **84.0**, which is effectively flat to slightly worse in this particular comparison. Relative to the cited reference result of **76.3** on SQuAD 2.0 and **84.3** on MNLI-m, the reimplementation itself is already competitive, and dynamic masking is described as “comparable or slightly better than static masking” ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Dynamic masking results

| Masking setup | SQuAD 2.0 (F1) | MNLI-m (Acc.) |
|---|---:|---:|
| Reference BERTBASE result | 76.3 | 84.3 |
| Reimplementation with static masking | 78.3 | 84.3 |
| Reimplementation with dynamic masking | 78.7 | 84.0 |

*Note. Results are medians over 5 seeds in the RoBERTa paper’s comparison. Source:* [Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf).

**Interpretation:** Dynamic masking matters, but modestly. On SQuAD 2.0 it yields a small gain; on MNLI it does not appear to be a major driver. This makes dynamic masking a sensible engineering improvement, not the main reason RoBERTa surpasses BERT ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## 2. Removing NSP and Changing Input Construction: Moderate Gains

The more interesting result is that RoBERTa revisits NSP and finds that performance improves when NSP is removed **if** training examples are constructed as longer contiguous text spans rather than artificial sentence pairs. This is important because BERT had earlier reported that removing NSP hurt MNLI and SQuAD, implying NSP was beneficial ([Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf)).

RoBERTa’s ablation shows the following on base models trained on BookCorpus + Wikipedia for 1M steps at batch size 256:

- **SEGMENT-PAIR with NSP**: SQuAD 2.0 F1 **78.7**, MNLI-m **84.0**
- **FULL-SENTENCES without NSP**: SQuAD 2.0 F1 **79.1**, MNLI-m **84.7**
- **DOC-SENTENCES without NSP**: SQuAD 2.0 F1 **79.7**, MNLI-m **84.7** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

### NSP and example-format ablation

| Pre-training format | NSP used? | SQuAD 1.1 (F1) | SQuAD 2.0 (F1) | MNLI-m (Acc.) |
|---|---|---:|---:|---:|
| SEGMENT-PAIR | Yes | 90.4 | 78.7 | 84.0 |
| SENTENCE-PAIR | Yes | 88.7 | 76.2 | 82.9 |
| FULL-SENTENCES | No | 90.4 | 79.1 | 84.7 |
| DOC-SENTENCES | No | 90.6 | 79.7 | 84.7 |
| Published BERTBASE | Yes | 88.5 | 76.3 | 84.3 |

*Note. All models in this table were trained for 1M steps with batch size 256 over BookCorpus and Wikipedia. Source:* [Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf).

These numbers support two conclusions.

First, **NSP is not inherently necessary** for strong SQuAD and MNLI performance. Once pre-training examples are built from more natural contiguous text, removing NSP is at least harmless and often helpful ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

Second, **input construction matters almost as much as the loss function itself**. The difference between SENTENCE-PAIR and DOC-SENTENCES is substantial: on SQuAD 2.0, **76.2 to 79.7** (+3.5 F1), and on MNLI-m, **82.9 to 84.7** (+1.8 accuracy points). Even compared with the stronger SEGMENT-PAIR baseline, DOC-SENTENCES still improves SQuAD 2.0 by **+1.0 F1** and MNLI-m by **+0.7** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

This is one of the most important findings in the paper. In my view, it shows that BERT’s original positive result for NSP was partly confounded by how examples were constructed, not solely by the value of the NSP loss itself.

## 3. More Data, Larger Batches, and Longer Training: The Biggest Gains

The largest improvements come from scaling the training recipe. RoBERTa reports a large-model series using the BERTLARGE architecture (24 layers, hidden size 1024, 16 attention heads, 355M parameters) and progressively changes data size and training duration ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Large-model scaling results

| Model/setup | Data | Batch size | Steps | SQuAD 1.1 (F1) | SQuAD 2.0 (F1) | MNLI-m (Acc.) |
|---|---|---:|---:|---:|---:|---:|
| BERTLARGE | Books + Wiki (~13 GB) | 256 | 1M | 90.9 | 81.8 | 86.6 |
| RoBERTa | Books + Wiki (~16 GB) | 8K | 100K | 93.6 | 87.3 | 89.0 |
| RoBERTa + additional data | ~160 GB | 8K | 100K | 94.0 | 87.7 | 89.3 |
| RoBERTa + pretrain longer | ~160 GB | 8K | 300K | 94.4 | 88.7 | 90.0 |
| RoBERTa + pretrain even longer | ~160 GB | 8K | 500K | 94.6 | 89.4 | 90.2 |

*Note. Source:* [Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf).

These are very large effects.

### Final gain over BERTLARGE

Using the strongest RoBERTa setup in this table versus BERTLARGE:

- **SQuAD 1.1 F1:** 94.6 vs. 90.9 = **+3.7**
- **SQuAD 2.0 F1:** 89.4 vs. 81.8 = **+7.6**
- **MNLI-m accuracy:** 90.2 vs. 86.6 = **+3.6** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

That is the clearest answer to “how much do the changes matter?” On SQuAD 2.0 especially, the answer is: **a lot**. A gain of 7.6 F1 is far larger than the gains from dynamic masking alone and larger than the gains from the NSP/input-format ablation alone. This strongly suggests that the dominant factor is not any one trick but the combination of **better optimization and more scale** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Which scaling factors mattered most within RoBERTa?

Within the RoBERTa scaling sequence:

- Adding more data at 100K steps improved SQuAD 2.0 from **87.3 to 87.7** (+0.4) and MNLI from **89.0 to 89.3** (+0.3).
- Extending training from 100K to 300K steps on the larger dataset improved SQuAD 2.0 from **87.7 to 88.7** (+1.0) and MNLI from **89.3 to 90.0** (+0.7).
- Extending again to 500K steps improved SQuAD 2.0 from **88.7 to 89.4** (+0.7) and MNLI from **90.0 to 90.2** (+0.2) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

So among the scaling factors shown here, **longer training appears more impactful than more data alone**, especially for SQuAD 2.0. The marginal returns do diminish, but they remain positive.

## End-task Results: What This Means on SQuAD and MNLI

RoBERTa’s end-task results further reinforce the point.

On **SQuAD development**, the reported single-model results are:

- **BERTLARGE:** 84.1 EM / 90.9 F1 on SQuAD 1.1; 79.0 EM / 81.8 F1 on SQuAD 2.0
- **XLNetLARGE:** 89.0 EM / 94.5 F1 on SQuAD 1.1; 86.1 EM / 88.8 F1 on SQuAD 2.0
- **RoBERTa:** 88.9 EM / 94.6 F1 on SQuAD 1.1; 86.5 EM / 89.4 F1 on SQuAD 2.0 ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

RoBERTa thus essentially matches XLNet on SQuAD 1.1 and surpasses it on SQuAD 2.0, while using only the provided SQuAD training data for fine-tuning rather than extra QA datasets ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

On **MNLI**, RoBERTa’s reported single-task single-model development result is **90.2/90.2**, compared with **86.6** for BERTLARGE and **89.8** for XLNetLARGE. On the GLUE test leaderboard, RoBERTa’s ensemble reaches **90.8/90.2** on MNLI, slightly ahead of XLNet’s **90.2/89.8** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## Overall Assessment

The evidence supports a clear ranking of importance among RoBERTa’s changes.

### Most important: scale and optimization
The largest gains on both SQuAD and MNLI come from **larger batches, more data, and longer training**. These changes produce multi-point improvements, including **+7.6 F1 on SQuAD 2.0** and **+3.6 accuracy on MNLI-m** relative to BERTLARGE in the cited large-model comparison ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Moderately important: removing NSP when paired with better text packing
Removing NSP matters, but not as a standalone trick. It becomes beneficial when combined with **full-sentence or document-sentence sampling**, which better matches the goal of learning from natural contiguous text. This change gives moderate but meaningful gains on SQuAD 2.0 and MNLI ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Least important among the highlighted changes: dynamic masking
Dynamic masking is useful and efficient, but the quantitative evidence suggests it is a **small improvement**, especially compared with scaling. On MNLI it is nearly neutral in the cited experiment; on SQuAD 2.0 it gives a small bump ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## Conclusion

RoBERTa changes BERT’s pre-training by removing NSP, adopting dynamic masking, pre-training on longer contiguous text, and scaling the entire training recipe through more data, much larger batches, and longer training. These changes matter significantly on SQuAD and MNLI, but their impact is highly uneven. The strongest evidence in the provided sources shows that the **big gains come from scale and optimization**, not from a radically different objective. Dynamic masking helps a little. Removing NSP helps when example construction is redesigned. But the dominant story is that BERT’s masked language modeling objective was already strong; RoBERTa unlocked more of its potential through better pre-training practice ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf); [Devlin et al., 2019](https://arxiv.org/pdf/1810.04805.pdf)).

In practical terms, if one asks what most improved SQuAD and MNLI performance, the answer is not “one clever loss.” It is **training the same basic idea much better**.

# References

Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). *Pre-training of deep bidirectional transformers for language understanding*. arXiv. [https://arxiv.org/pdf/1810.04805.pdf](https://arxiv.org/pdf/1810.04805.pdf)

Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., Lewis, M., Zettlemoyer, L., & Stoyanov, V. (2019). *RoBERTa: A robustly optimized BERT pretraining approach*. arXiv. [https://arxiv.org/pdf/1907.11692.pdf](https://arxiv.org/pdf/1907.11692.pdf)