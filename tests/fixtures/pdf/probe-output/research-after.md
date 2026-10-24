# How RoBERTa Changes BERT’s Pre-Training, and How Much Those Changes Matter on SQuAD and MNLI

## Overview

RoBERTa is best understood not as a fundamentally new language model architecture, but as a stronger and more carefully optimized version of BERT pre-training. The central claim of the RoBERTa paper is that BERT had been systematically undertrained and that several seemingly secondary training choices—more data, longer training, larger batches, dynamic masking, longer sequences, and removal of the next sentence prediction (NSP) objective—substantially improve downstream task performance without changing BERT’s core masked language modeling framework ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

On the specific question of **how much these changes matter on SQuAD and MNLI**, the answer is: **a great deal overall, but unevenly across individual changes**. The largest gains in the provided evidence come from **scaling and optimization**—especially **more pre-training data** and **more training steps**—while **dynamic masking** appears to provide only a modest, mixed gain in isolation under short-training conditions. RoBERTa’s final reported improvements over BERT are particularly large on **SQuAD 2.0** and clearly meaningful on **MNLI**, suggesting that BERT’s pre-training recipe, more than its architecture, was the main bottleneck ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## BERT’s Original Pre-Training Recipe

BERT was originally trained with two pre-training tasks: **masked language modeling (MLM)** and **next sentence prediction (NSP)**. The MLM objective learns bidirectional contextual representations by masking tokens and predicting them. NSP, in contrast, is a sentence-pair objective intended to teach inter-sentence relationships. In BERT’s own ablation experiments, removing NSP hurt performance substantially on tasks including **MNLI** and **SQuAD 1.1**, which initially supported the inclusion of NSP in the standard BERT recipe ([Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)).

BERT also used a **static masking** scheme during pre-processing. The original implementation masked each training sequence once, then duplicated the data ten times so that each sequence appeared with ten different masking patterns over forty epochs. Even so, each sequence was seen with the same mask multiple times during training, which limited mask diversity relative to a dynamic scheme ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

This original setup became the baseline that RoBERTa revisited. Importantly, RoBERTa’s contribution is not to replace MLM with a radically different objective, but to show that BERT’s masked-language-model pre-training remains highly competitive if the training pipeline is properly optimized ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## What RoBERTa Changes in BERT Pre-Training

## 1. It removes the NSP objective

RoBERTa explicitly removes the **next sentence prediction** task from BERT’s pre-training recipe and relies only on MLM. In the RoBERTa paper’s conclusion, the authors identify “removing the next sentence prediction objective” as one of the changes that substantially improved performance in their overall training framework ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

This is notable because it appears to contradict BERT’s earlier ablation, where removing NSP hurt MNLI and SQuAD 1.1 ([Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)). The most defensible interpretation is that **NSP was not intrinsically beneficial in all settings**, but rather that its apparent value in BERT depended on the rest of BERT’s training configuration. RoBERTa’s results imply that once the model is trained longer, on more data, with larger batches and a better masking strategy, NSP is no longer necessary and may even be a distraction from the main MLM objective ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf); [Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)).

## 2. It replaces static masking with dynamic masking

RoBERTa changes BERT’s token masking from **static** to **dynamic**. Under dynamic masking, the mask pattern is generated each time a sequence is fed to the model, so the same text can be seen under many more masking patterns over the course of training. The RoBERTa authors argue that this becomes especially important when pre-training is extended for more steps or over larger datasets ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

The isolated effect of dynamic masking in the excerpted ablation is **modest and mixed**:

| Masking strategy | SQuAD 2.0 | MNLI-m | SST-2 |
|---|---:|---:|---:|
| Reference | 76.3 | 84.3 | 92.8 |
| Reimplementation: static | 78.3 | 84.3 | 92.5 |
| Reimplementation: dynamic | 78.7 | 84.0 | 92.9 |

*Note. Results reported in the RoBERTa ablation excerpt. Source: ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).*

From these numbers, dynamic masking improved **SQuAD 2.0 by 0.4 points** relative to the RoBERTa static reimplementation, slightly **decreased MNLI-m by 0.3**, and improved **SST-2 by 0.4** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)). Therefore, dynamic masking appears useful, but the evidence provided here suggests it is **not the main driver** of RoBERTa’s gains on SQuAD and MNLI by itself.

## 3. It trains much longer

One of RoBERTa’s clearest changes is simply **more pre-training steps**. The paper reports large gains when increasing training from **100K steps** to **300K**, and then to **500K**, while keeping the larger pre-training corpus and batch size fixed ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## 4. It uses more pre-training data

RoBERTa scales pre-training data from a BooksCorpus+Wikipedia setup to a much larger **160GB** corpus by adding three additional datasets, including the newly introduced **CC-NEWS** corpus. The authors report consistent improvements across downstream tasks when moving from the smaller corpus to the larger one ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## 5. It uses much larger batch sizes

RoBERTa pre-trains with a **batch size of 8K**, compared with the **256** used for BERT\(_{\text{LARGE}}\) in the comparison table. This difference is part of the paper’s broader claim that BERT benefits from “training the model longer, with bigger batches over more data” ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## 6. It trains on longer sequences

In the conclusion, RoBERTa identifies **training on longer sequences** as another important design decision that improves performance, although the provided excerpts do not include a task-by-task ablation table for this factor alone ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## How Much These Changes Matter on SQuAD and MNLI

The most informative evidence comes from the controlled comparison table reproduced in the provided excerpts. RoBERTa uses the **same BERT\(_{\text{LARGE}}\) architecture** but alters the training recipe.

| Model | Data size | Batch size | Steps | SQuAD (v1.1 / v2.0) | MNLI-m | SST-2 |
|---|---:|---:|---:|---:|---:|---:|
| RoBERTa with BOOKS + WIKI | 16GB | 8K | 100K | 93.6 / 87.3 | 89.0 | 95.3 |
| + additional data | 160GB | 8K | 100K | 94.0 / 87.7 | 89.3 | 95.6 |
| + pretrain longer | 160GB | 8K | 300K | 94.4 / 88.7 | 90.0 | 96.1 |
| + pretrain even longer | 160GB | 8K | 500K | 94.6 / 89.4 | 90.2 | 96.4 |
| BERT\(_{\text{LARGE}}\) with BOOKS + WIKI | 13GB | 256 | 1M | 90.9 / 81.8 | 86.6 | 93.7 |
| XLNet\(_{\text{LARGE}}\) with BOOKS + WIKI | 13GB | 256 | 1M | 94.0 / 87.8 | 88.4 | 94.4 |
| XLNet\(_{\text{LARGE}}\) + additional data | 126GB | 2K | 500K | 94.5 / 88.8 | 89.8 | 95.6 |

*Note. Results as reported in the provided RoBERTa comparison excerpt. Source: ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).*

### Overall gain over BERT on SQuAD and MNLI

Comparing **BERT\(_{\text{LARGE}}\)** to the best **RoBERTa** model in the table shows the full practical impact of the changed pre-training recipe:

- **SQuAD v1.1:** 90.9 → 94.6 (**+3.7**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **SQuAD v2.0:** 81.8 → 89.4 (**+7.6**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **MNLI-m:** 86.6 → 90.2 (**+3.6**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

These are not marginal gains. A **3.6-point increase on MNLI** and especially a **7.6-point increase on SQuAD 2.0** represent substantial downstream improvements for benchmark tasks of this maturity ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

### Effect of more data

Holding steps at **100K** and batch size at **8K**, expanding from **16GB** to **160GB** improved:

- **SQuAD v1.1:** 93.6 → 94.0 (**+0.4**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **SQuAD v2.0:** 87.3 → 87.7 (**+0.4**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **MNLI-m:** 89.0 → 89.3 (**+0.3**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

These are real but moderate gains, suggesting that **data scale helps, but more data alone is not the whole story**.

### Effect of longer training

Keeping the large 160GB corpus and 8K batch size, increasing training from **100K** to **300K** steps improved:

- **SQuAD v1.1:** 94.0 → 94.4 (**+0.4**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **SQuAD v2.0:** 87.7 → 88.7 (**+1.0**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **MNLI-m:** 89.3 → 90.0 (**+0.7**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

Increasing again from **300K** to **500K** steps yielded:

- **SQuAD v1.1:** 94.4 → 94.6 (**+0.2**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **SQuAD v2.0:** 88.7 → 89.4 (**+0.7**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))
- **MNLI-m:** 90.0 → 90.2 (**+0.2**) ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf))

This pattern strongly suggests that **longer training is one of the most important contributors**, especially for **SQuAD 2.0**, where gains continue to accumulate meaningfully even beyond 300K steps ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## SQuAD-Specific Significance

RoBERTa’s SQuAD results are especially notable because the authors emphasize that they used a **simpler fine-tuning approach** than prior work. Unlike both BERT and XLNet, which augmented training with **additional QA datasets**, RoBERTa was fine-tuned using **only the provided SQuAD training data** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

On the development sets, RoBERTa **matched XLNet on SQuAD v1.1** and established a **new state of the art on SQuAD v2.0**, improving over XLNet by **0.4 EM** and **0.6 F1** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)). This matters for interpreting the pre-training recipe: it shows that stronger pre-training can offset the lack of extra task-specific data during fine-tuning.

My concrete assessment is that **SQuAD is where RoBERTa’s recipe changes matter most visibly** in the provided evidence. The leap from **81.8 to 89.4 on SQuAD 2.0** versus BERT is too large to dismiss as routine variance, and the fact that it is achieved without extra QA data strengthens the case that the gains arise from pre-training quality rather than downstream engineering alone ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

## MNLI-Specific Significance

MNLI shows a different pattern: the gains are clearly real, but they are **more incremental** than on SQuAD 2.0. Relative to BERT\(_{\text{LARGE}}\), RoBERTa improves **MNLI-m from 86.6 to 90.2**, a **+3.6 point** increase ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)). This is still substantial in benchmark terms, and RoBERTa was reported to establish a new state of the art on MNLI among GLUE tasks ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

However, compared with SQuAD, MNLI appears less sensitive to isolated tweaks like dynamic masking; in the masking ablation, dynamic masking slightly reduced MNLI-m from **84.3 to 84.0** compared with the static reimplementation ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)). This reinforces a broader conclusion: **the MNLI gains are primarily the result of the full optimized recipe rather than any single change**.

## Interpreting the Contradiction Around NSP

A particularly important interpretive issue is the contrast between BERT and RoBERTa on NSP. BERT originally found that removing NSP hurt **MNLI** and **SQuAD 1.1** ([Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)). RoBERTa later concluded that removing NSP was part of a better training recipe overall ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

The most reasonable conclusion is not that one paper is simply “right” and the other “wrong,” but that **the value of NSP is conditional on the rest of the training setup**. In BERT’s more limited optimization regime, NSP may have supplied useful learning signal. In RoBERTa’s better-optimized regime, it was apparently unnecessary. This makes RoBERTa’s broader lesson more important than the NSP debate itself: **training protocol can dominate objective-level differences** ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf); [Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)).

## Bottom-Line Judgment

Based on the provided evidence, the strongest and most defensible opinion is this:

**RoBERTa’s gains over BERT on SQuAD and MNLI come mainly from better optimization and scale, not from a radically different learning objective.** The headline changes that matter most are **more data**, **larger batches**, and especially **longer pre-training**. **Dynamic masking** helps somewhat but appears modest in isolation, and **removing NSP** should be viewed as part of a successful package rather than as a universally beneficial standalone change ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf); [Devlin et al., 2018](https://arxiv.org/pdf/1810.04805.pdf)).

For the tasks in question, these changes matter **substantially**:

- On **SQuAD v2.0**, the total improvement over BERT is **+7.6 points**, which is very large ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
- On **SQuAD v1.1**, the gain is **+3.7 points**, also large ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).
- On **MNLI-m**, the gain is **+3.6 points**, clearly meaningful ([Liu et al., 2019](https://arxiv.org/pdf/1907.11692.pdf)).

In short, RoBERTa shows that a large fraction of what later appeared to be “architectural progress” in NLP was actually recoverable within BERT’s original MLM framework by training it much more effectively.

## References

Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2018). *BERT: Pre-training of deep bidirectional transformers for language understanding*. arXiv. [https://arxiv.org/pdf/1810.04805.pdf](https://arxiv.org/pdf/1810.04805.pdf)

Liu, Y., Ott, M., Goyal, N., Du, J., Joshi, M., Chen, D., Levy, O., Lewis, M., Zettlemoyer, L., & Stoyanov, V. (2019). *RoBERTa: A robustly optimized BERT pretraining approach*. arXiv. [https://arxiv.org/pdf/1907.11692.pdf](https://arxiv.org/pdf/1907.11692.pdf)

## Source URLs

- [https://arxiv.org/pdf/1810.04805.pdf](https://arxiv.org/pdf/1810.04805.pdf)
- [https://arxiv.org/pdf/1907.11692.pdf](https://arxiv.org/pdf/1907.11692.pdf)