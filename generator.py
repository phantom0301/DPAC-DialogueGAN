### TODO
# Teacher forcing


import torch
import torch.autograd as autograd
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pdb
import math
import torch.nn.init as init
from EncoderDecoderAttn import Encoder, Decoder
import random

class Generator(nn.Module):

    def __init__(self, vocab_size, hidden_size, embed_size, max_len, enc_n_layers=2, \
        enc_dropout=0.2, dec_n_layers=2, dec_dropout=0.2, device='cpu'):
        super(Generator, self).__init__()

        encoder = Encoder(vocab_size, embed_size, hidden_size, enc_n_layers, enc_dropout)
        decoder = Decoder(embed_size, hidden_size, vocab_size, dec_n_layers, dec_dropout)

        self.device = device
        self.encoder = encoder
        self.decoder = decoder


    def forward(self, src, tgt, EOU, teacher_forcing_ratio=0.5):
        batch_size = src.size(1)
        max_len = tgt.size(0)
        vocab_size = self.decoder.output_size
        outputs = autograd.Variable(torch.zeros(max_len, batch_size, vocab_size)).to(self.device)

        encoder_output, hidden = self.encoder(src)
        hidden = hidden[:self.decoder.n_layers]
        SOS = tgt.data[0, :]
        output = autograd.Variable(SOS)
        for t in range(1, max_len):
            output, hidden, attn_weights = self.decoder(
                    output, hidden, encoder_output)
            outputs[t] = output
            is_teacher = random.random() < teacher_forcing_ratio
            top1 = output.data.max(1)[1]
            output = autograd.Variable(tgt.data[t] if is_teacher else top1).to(self.device)
        return outputs

    def sample(self, context, max_len):
        """
        Samples the network using a batch of source input sequence. Passes these inputs
        through the decoder and instead of taking the top1 (like in forward), sample
        using the distribution over the vocabulary


        Inputs: dialogue context and maximum sample sequence length
        Outputs: samples
        samples: num_samples x max_seq_length (a sampled sequence in each row)

        Inputs: dialogue context (and maximum sample sequence length
        Outputs: samples
            - samples: num_samples x max_seq_length (a sampled sequence in each row)"""

        # Initialize sample
        batch_size = context.size(1)
        vocab_size = self.decoder.output_size
        samples = autograd.Variable(torch.zeros(batch_size,max_len)).to(self.device)
        samples_prob = autograd.Variable(torch.zeros(batch_size, max_len)).to(self.device)

        # Run input through encoder
        encoder_output, hidden = self.encoder(context)
        hidden = hidden[:self.decoder.n_layers]
        output = autograd.Variable(context.data[0, :])  # sos
        samples[:,0] = output
        samples_prob[:,0] = torch.ones(output.size())

        # Pass through decoder and sample from resulting vocab distribution
        for t in range(1, max_len):
            output, hidden, attn_weights = self.decoder(
                    output, hidden, encoder_output)

            # Sample token for entire batch from predicted vocab distribution
            batch_token_sample = torch.multinomial(torch.exp(output), 1).view(-1).data
            prob = torch.exp(output).gather(1, batch_token_sample.unsqueeze(1)).view(-1).data
            samples_prob[:, t] = prob
            samples[:, t] = batch_token_sample
            output = autograd.Variable(batch_token_sample)
        return samples, samples_prob

    def batchNLLLoss(self, inp, target):
        """
        Returns the NLL Loss for predicting target sequence.

        Inputs: inp, target
            - inp: batch_size x seq_len
            - target: batch_size x seq_len

            inp should be target with <s> (start letter) prepended
        """

        loss_fn = nn.NLLLoss()
        batch_size, seq_len = inp.size()
        inp = inp.permute(1, 0)           # seq_len x batch_size
        target = target.permute(1, 0)     # seq_len x batch_size
        h = self.init_hidden(batch_size)

        loss = 0
        for i in range(seq_len):
            out, h = self.forward(inp[i], h)
            loss += loss_fn(out, target[i])

        return loss     # per batch

    def batchPGLoss(self, inp, target, reward, word_probabilites):
        """
        Returns a pseudo-loss that gives corresponding policy gradients (on calling .backward()).
        Inspired by the example in http://karpathy.github.io/2016/05/31/rl/

        Inputs: inp, target
            - inp: batch_size x seq_len
            - target: batch_size x seq_len
            - reward: batch_size (discriminator reward for each sentence, applied to each token of the corresponding
                      sentence)

            inp should be target with <s> (start letter) prepended
        """

        batch_size, max_len = target.shape
        loss = 0

        for batch in range(batch_size):
            for word in range(max_len):
                loss += word_probabilites[batch][word].log() * reward[batch] # Montecarlo add reward per word (reward[batch][word])

        # loss = 0
        # for i in range(seq_len):
        #     out, h = self.forward(inp[i], h)
        #     # TODO: should h be detached from graph (.detach())?
        #     for j in range(batch_size):
        #         loss += -out[j][target.data[i][j]]*reward[j]     # log(P(y_t|Y_1:Y_{t-1})) * Q
        loss = -torch.mean(loss)
        return loss
