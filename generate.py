#!/usr/bin/python3

import argparse
import os, sys
import numpy as np


parser = argparse.ArgumentParser(description = "A Python script that generates startup names."
                                 "It takes as input a text file containing some "
                                 "list of words, e.g. a German book chapter, a Greek dictionary, or a list of Pokemon "
                                 "(it doesn't have to be formatted, the script contains a rudimentary "
                                 "preprocessing step). The script then trains a recurrent neural network to learn "
                                 "the structure of the words, and finally outputs a list of suggestions with "
                                 "a similar structure as the words in the provided wordlist.")
parser.add_argument("wordlist",
                    help="Path to the word list, a not necessarily well-formatted .txt file")
parser.add_argument("-s", "--savepath",
                    help="Path to save the computed model")
parser.add_argument("-m", "--modelpath",
                    help="Don't compute a model, instead load a previously computed one from this path")
parser.add_argument("-t", "--temperature", type = float, default = 1.0,
                    help="The randomness with which to sample the words' characters. Range from zero to " 
                    "inifinity, but a value between 0.5 (conservative) and 1.5 (more random) is recommended. "
                    "Defaults to 1.0")
parser.add_argument("-n", "--nwords", type = int, default = 10,
                    help="Number of words to sample. Default 10.")
parser.add_argument("-e", "--epochs", type = int, default = 100,
                    help="Number of epochs to train the model. Default 100, but try up to 500")
parser.add_argument("-v", "--verbose",
                    help="Report more details", action = "store_true")

args = parser.parse_args()

# Don't print the many warnings
# https://github.com/h5py/h5py/issues/961
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=DeprecationWarning)
import h5py
# warnings.resetwarnings()

# Don't print the "Using TensorFlow backend"
# https://github.com/keras-team/keras/issues/1406
stderr = sys.stderr
sys.stderr = open(os.devnull, 'w')
import keras
sys.stderr = stderr

from keras.models import Sequential
from keras.layers import Dense, Activation
from keras.layers import LSTM, SimpleRNN, GRU, TimeDistributed
from keras.callbacks import LambdaCallback

from preprocess import text_to_words

   
# Generate a list of words (including newline)
words = text_to_words(args.wordlist)

# Generate the set of unique characters (including newline)
# https://stackoverflow.com/questions/952914/making-a-flat-list-out-of-list-of-lists-in-python
chars = sorted(list(set([char for word in words for char in word])))

VOCAB_SIZE = len(chars)
N_WORDS = len(words)  # #words in corpus - not #words to generate
MAX_WORD_LEN = 12  # maximum company name length

if args.verbose:
    print(N_WORDS, "words\n")
    print("vocabulary of", len(chars), "characters, including the \\n:")
    print(chars)
    print("\nFirst two sample words:")
    print(words[0:2])

ix_to_char = {ix:char for ix, char in enumerate(chars)}
char_to_ix = {char:ix for ix, char in enumerate(chars)}

X = np.zeros((N_WORDS, MAX_WORD_LEN, VOCAB_SIZE))
Y = np.zeros((N_WORDS, MAX_WORD_LEN, VOCAB_SIZE))

for word_i in range(N_WORDS):
    word = words[word_i]
    chars = list(word)
    word_len = len(word)
    
    for char_j in range(min(len(word), MAX_WORD_LEN)):
        char = chars[char_j]
        char_ix = char_to_ix[char]
        X[word_i, char_j, char_ix] = 1
        if char_j > 0:
            Y[word_i, char_j - 1, char_ix] = 1  # the 'next char' at time point char_j

LAYER_NUM = 2
HIDDEN_DIM = 50

model = Sequential()
model.add(LSTM(HIDDEN_DIM, input_shape=(None, VOCAB_SIZE), return_sequences=True))
for i in range(LAYER_NUM - 1):
    model.add(LSTM(HIDDEN_DIM, return_sequences=True))
model.add(TimeDistributed(Dense(VOCAB_SIZE)))
model.add(Activation('softmax'))
model.compile(loss="categorical_crossentropy", optimizer="rmsprop")

def temp_scale(probs, temperature = 1.0):
    # a low temperature (< 1 and approaching 0) results in the char sampling approaching the argmax.
    # a high temperature (> 1, approaching infinity) results in sampling from a uniform distribution)
    probs = np.exp(np.log(probs) / temperature)
    probs = probs / np.sum(probs)
    return probs
    
    
def generate_word(model, temperature = 1.0, min_word_length = 4):
    X = np.zeros((1, MAX_WORD_LEN, VOCAB_SIZE))
    
    # sample the first character
    initial_char_distribution = temp_scale(model.predict(X[:, 0:1, :]).flatten(), temperature)
    
    ix = 0
    while ix == 0:  # make sure the initial character is not a newline (i.e. index 0)
        ix = int(np.random.choice(VOCAB_SIZE, size = 1, p = initial_char_distribution))
    
    X[0, 0, ix] = 1
    generated_word = [ix_to_char[ix].upper()]  # start with first character, then later successively append chars
    
    # sample all remaining characters
    for i in range(1, MAX_WORD_LEN):
        next_char_distribution = temp_scale(model.predict(X[:, 0:i, :])[:, i-1, :].flatten(), temperature)

        
        ix_choice = np.random.choice(VOCAB_SIZE, size = 1, p = next_char_distribution)
        # ix_choice = np.argmax(next_char_distribution)  # <- corresponds to sampling with a very low temperature
        ctr = 0
        while ix_choice == 0 and i < min_word_length:
            ctr += 1
            # sample again if you picked the end-of-word token too early
            ix_choice = np.random.choice(VOCAB_SIZE, size = 1, p = next_char_distribution)
            if ctr > 1000:
                print("caught in a near-infinite loop. You might have picked too low a temperature "
                      "and the sampler just keeps sampling \\n's")
                break
            
        
        next_ix = int(ix_choice)
        X[0, i, next_ix] = 1
        if next_ix == 0:
            break
        generated_word.append(ix_to_char[next_ix])
    
    return ('').join(generated_word)


def on_epoch_end(epoch, logs):
    if epoch % 50 == 0 and args.verbose:
        print("epoch " + str(epoch) + ": " + generate_word(model, temperature = 1.0, min_word_length = 4))


print_callback = LambdaCallback(on_epoch_end = on_epoch_end)

NUM_EPOCHS = 500
BATCH_SIZE = 64  # or: N_WORDS

if args.modelpath != None:
    ## Load one of these models if you have trained them before and want to skip re-training
    model = keras.models.load_model(args.modelpath)
else:
    model.fit(X, Y, batch_size = BATCH_SIZE, verbose = 0, epochs = NUM_EPOCHS, callbacks = [print_callback])

    if args.savepath != None:
        model.save(args.savepath)

# Print a few words with the final model:

for _ in range(args.nwords):
    print(generate_word(model, temperature = args.temperature, min_word_length = 4))
