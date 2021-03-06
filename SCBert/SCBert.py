#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed May  6 11:49:32 2020

Sentence Clustering with pretrained BERT models

@author: kevin
"""
import torch
from transformers import FlaubertModel,FlaubertTokenizer, FlaubertConfig
from transformers import CamembertModel,CamembertTokenizer, CamembertConfig
import numpy as np 
from tqdm import tqdm
from sklearn.cluster import KMeans
from stop_words import get_stop_words
from multi_rake import Rake
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt

MODELS = {"flaubert" : {
                  "model" : FlaubertModel,
                  "tokenizer" : FlaubertTokenizer,
                  "config" : FlaubertConfig, 
                  "pad_id" : 2,
                  "model_name" : 'flaubert-base-uncased'},
          "camembert" : {
                  "model" : CamembertModel,
                  "tokenizer" : CamembertTokenizer,
                  "config" : CamembertConfig, 
                  "pad_id" : 1,
                  "model_name" : 'camembert-base'}}

class Vectorizer :
        
        def __init__(self, model_name = "flaubert") :
            """
            Constructor of the vectorizer object used to transform your texts into vectors using french BERT models. 

            Parameters
            ----------
            model_name : string, optional
                Corresponds to the model you want to use to tokenize and vectorize your data. Only CamemBERT and Flaubert small for now. 
                DESCRIPTION. The default is "flaubert".
                
            MAX_LEN : int, optional
                Corresponds to the max number of word to take into account during tokenizing. If a text is 350 words long and 
                MAX_LEN is 256, the text will be truncated after the 256th word, starting at the beginning of the sentence. 
                DESCRIPTION. The default is 256.
            ----------

            """
            self.model_dict = MODELS[model_name.lower()]
            self.model = self.model_dict["model"].from_pretrained(self.model_dict["model_name"],  output_hidden_states=True)
            self.tokenizer = self.model_dict["tokenizer"].from_pretrained(self.model_dict["model_name"])
            self.pad_id = self.model_dict["pad_id"]

        
        
        def tokenize (self, data, MAX_LEN = 256) :
            """
            This function call the tokenizer corresponding to the BERT model specified in the constructor. Then it generates
            a vector of id corresponding to the words in the vocabulary. Also an attention vector which has the same size as the vector of id with ones 
            for real words and zeros corresponding to padding id. 
            
            Parameters
            ----------
            data : `Numpy array` or `Pandas DataFrame`
                Corresponds to your datas, must be a list of your texts texts. 
                
            MAX_LEN : int, optional
                Corresponds to the max number of word to take into account during tokenizing. If a text is 350 words long and 
                MAX_LEN is 256, the text will be truncated after the 256th word, starting at the beginning of the sentence. 
                Default: The default is 256.
                

            Returns
            -------
            tokenized_texts : List of list of strings
                Corresponds of the list of your tokenized texts. Each text has been transformed into a vector of word according the tokenizer of the BERT model stated into the constructor.
            input_ids_tensor : List of List of int
                Same as tokenized_texts but with ids corresponding to the tokens, converted into torch tensor. 
            masks_tensor : List of list of float
                Corresponds to the attention torch tensor
            """
            tokenized_texts = np.array([self.tokenizer.tokenize(text) for text in data])
            input_ids = np.array([self.tokenizer.encode(text, max_length=MAX_LEN, pad_to_max_length=True,  add_special_tokens= True ) for text in data])
            # Create attention masks
            attention_masks = []
          
            # Create a mask of 1s for each token followed by 0s for padding
            for seq in input_ids:
                seq_mask = [float(i != self.pad_id) for i in seq]
                attention_masks.append(seq_mask)
          
            # Convert all of our data into torch tensors, the required datatype for our model
            input_ids_tensor = torch.tensor(input_ids)
            masks_tensor = torch.tensor(attention_masks)
            
            return tokenized_texts, input_ids_tensor, masks_tensor
        
        def __sentence_pooling (self, vectors , pooling_method) :
            """
            Parameters
            ----------
            vectors : list of vectors representing each words including the BOS and EOS tag
            
            pooling_method : string
                average or max.

            Returns
            -------
            pooled_vectors : tensor 
                pooled tensors according to the method.

            """

            pooled_vector = torch.tensor([])
            if pooling_method.lower() == "average" :
                pooled_vector = torch.mean(vectors, axis=0)
                
            elif pooling_method.lower() == "max" :
                pooled_vector = torch.max(vectors, axis=0)
            
            return pooled_vector
        
        def __word_pooling (self, encoded_layers_b, layers, idx,  pooling_method) :
            """
            Parameters
            ----------
            vectors : list of vectors representing each words including the BOS and EOS tag
            
            pooling_method : string
                average, max or concat.

            Returns
            -------
            pooled_words : tensor 
                pooled tensors according to the method.

            """
            pooled_words = torch.tensor([])
            
            if pooling_method.lower() == "concat" :
                for layer in layers :   
                    pooled_words = torch.cat((pooled_words, encoded_layers_b[layer][idx]), dim=1)
                    
            if pooling_method.lower() == "average" :
                pooled_words = torch.tensor([[0. for i in range(768)] for j in range(256)])
                for layer in layers :
                    pooled_words = pooled_words.add(encoded_layers_b[layer][idx])
                pooled_words = pooled_words/(len(layers))
                
            elif pooling_method.lower() == "max" :
                pooled_words = torch.tensor([[-100. for i in range(768)] for j in range(256)])
                for layer in layers :   
                    pooled_words = torch.max(pooled_words, encoded_layers_b[layer][idx])
            
            return pooled_words
        
        def __batch(self, iterable, n=1):
            l = len(iterable)
            for ndx in range(0, l, n):
                yield iterable[ndx:min(ndx + n, l)]
                
        def forward_and_pool (self, input_ids_tensor, masks_tensor, sentence_pooling_method="average", word_pooling_method="average", layers = 11, batch_size=50, path_to_save=None) :
            """
            This function execute the forward pass of the input data into the BERT model and create a unique tensor for each input according to the stated pooling methods. 
            
            Parameters
            ----------
            input_ids_tensor : tensor
                Corresponds to then= ids of tokenized words. 
                Must match the output of the tokenize function.
            masks_tensor : tensor
                Corresponds to the attention masks of tokenized words. 
                Must match the output of the tokenize function. .
            sentence_pooling_method : str, optional
                Corresponds to the method of pooling to create a unique vector for each text
                The default is "average".
            word_pooling_method : str, optional
                Corresponds to the method of word pooling method in the case multiple layers have been stated. In other words it is the way to compute a single word vector from multiple layers.
                The default is "average".
            layers : int or list, optional
                Corresponds to the BERT layers to use to create the embeddings of words.
                The default is 11.
            batch_size : int, optional
                Size of batch when executing the forward pass into the BERT model, should get lower as your computational power gets lower. 
                The default is 50.
            path_to_save : str or None, optional
                Is the path to save the vector of texts if you want to avoid doing this computation again as it may be long. 
                if None, nothing will be saved. 
                The default is None.
            
            Returns
            -------
            texts_vectors : list
                A list of tensors, each tensor corresponding to an input text.

            """
            
            layer_list = False
            if (sentence_pooling_method not in ["average", "max"]) :
                raise ValueError('sentence_pooling_method must be equal to `average` or `max`')
                
            if (word_pooling_method not in ["average", "max", "concat"]) :
                raise ValueError('word_pooling_method must be equal to `average`, `max` or `concat` ')
            
            if(type(batch_size) != int) :
                raise TypeError('batch_size must be a positive integer')
                
            if(batch_size<=0) :
                raise ValueError('batch_size must be a positive integer')
                
            if((type(path_to_save)  != str ) and (path_to_save != None)):
                raise TypeError('path_to_save must be None or a string')
                
            if (type(layers) != int) :
                if (type(layers) == list) :
                    layer_list = True
                    for el in layers : 
                        if (type(el) != int) :
                            raise TypeError('layers must be a int between 1 and 12 or a list of integers between 1 and 12')
                        elif (el>12 or el<1) :
                            raise ValueError('layers must be a int between 1 and 12 or a list of integers between 1 and 12')
                else :
                    raise TypeError('layers must be a int between 1 and 12 or alist of integers between 1 and 12')
            else :
                if (layers>12 or layers<1) :
                    raise ValueError('layers must be a int between 1 and 12 or a list of integers between 1 and 12')
            
            texts_vectors = []
            N = len(input_ids_tensor)
            counter = 0
            with tqdm(total = 100) as pbar : 
                for b in self.__batch(range(0,N), batch_size) :
                    with torch.no_grad() :
                        encoded_layers_b = self.model(input_ids_tensor[b], masks_tensor[b].to(torch.int64))[1]
                            
                        if layer_list :
                            for idx in b :
                                if input_ids_tensor[idx][-1]==1 :
                                    eos_pos = 0
                                else :
                                    eos_pos = int((input_ids_tensor[idx] == self.pad_id).nonzero()[0])
                                word_vector = self.__word_pooling(encoded_layers_b, layers, idx - counter, word_pooling_method)
                                pooled_vector = self.__sentence_pooling(word_vector[:eos_pos-1][1:], sentence_pooling_method) #Just no to take into account BOS and EOS 
                                texts_vectors.append(pooled_vector)
                            
                        else : 
                            words_vector = encoded_layers_b[layers]
                            
                            for idx in b : 
                                if input_ids_tensor[idx][-1]==1 :
                                    eos_pos = 0
                                else :
                                    eos_pos = int((input_ids_tensor[idx] == self.pad_id).nonzero()[0])
                                pooled_vectors = self.__sentence_pooling(words_vector[idx-counter][:eos_pos-1][1:], sentence_pooling_method) #Just no to take into account BOS and EOS 
                                for i, sentence in enumerate(pooled_vectors) :
                                    texts_vectors.append(pooled_vectors[i])
                    counter += batch_size
                    pbar.update(np.round(100*len(b)/N,2))
            
            if path_to_save != None : 
              torch.save(texts_vectors, path_to_save+"text_vectors")
            
            return texts_vectors


        def vectorize (self, data, MAX_LEN = 256, sentence_pooling_method="average", word_pooling_method="average", layers = 11, batch_size=50, path_to_save=None) :
            """
            Transform the input raw data into tensors according to the selected models and the pooling methods. 
            
            Parameters
            ----------
            data : `Numpy array` or `Pandas DataFrame`
                Corresponds to your datas, must be a list of your texts texts. 
                
            MAX_LEN : int, optional
                Corresponds to the max number of word to take into account during tokenizing. If a text is 350 words long and 
                MAX_LEN is 256, the text will be truncated after the 256th word, starting at the beginning of the sentence. 
                Default: The default is 256.
            sentence_pooling_method : str, optional
                Corresponds to the method of pooling to create a unique vector for each text
                The default is "average".
            word_pooling_method : str, optional
                Corresponds to the method of word pooling method in the case multiple layers have been stated. In other words it is the way to compute a single word vector from multiple layers.
                The default is "average".
            layers : int or list, optional
                Corresponds to the BERT layers to use to create the embeddings of words.
                The default is 11.
            batch_size : int, optional
                Size of batch when executing the forward pass into the BERT model, should get lower as your computational power gets lower. 
                The default is 50.
            path_to_save : str or None, optional
                Is the path to save the vector of texts if you want to avoid doing this computation again as it may be long. 
                if None, nothing will be saved. 
                The default is None.

            Returns
            -------
            texts_vectors : list
                A list of tensors, each tensor corresponding to an input text.

            """
            tokenized_texts, input_ids_tensor, masks_tensor = self.tokenize(data,MAX_LEN)
            texts_vectors = self.forward_and_pool(input_ids_tensor,masks_tensor,sentence_pooling_method,word_pooling_method,layers,batch_size,path_to_save)
            
            return texts_vectors
        
class EmbeddingExplorer :
    
    def __init__(self,data, texts_vectors) :
        self.data = data
        self.texts_vectors = np.array([el.tolist() for el in texts_vectors])
        self.labels = [0 for i in range (len(texts_vectors))]
        self.keywords = {}

    def cluster (self, k, cluster_algo="k-means") :
        clf = KMeans(n_clusters=k,
              max_iter=50,
              init='k-means++',
              n_init=4)
        self.labels = clf.fit_predict(self.texts_vectors)

        return self.labels
    
    def extract_keywords(self, num_top_words=10) :

        stop_words = get_stop_words('fr')  
        
        rake = Rake(max_words=1, min_freq = 3, language_code ="fr", stopwords = stop_words)
        
        for i, label in enumerate(np.unique(self.labels)):
              corpus_fr = ' '.join(self.data[self.labels==label])
              keywords = rake.apply(corpus_fr)
              top_words= np.array(keywords[:num_top_words])[:,0]
              self.keywords["Cluster {0}".format(label)] = top_words
              
        return self.keywords
    
    def explore(self, color) :

        pca = PCA(n_components=2).fit(self.texts_vectors)
        datapoint = pca.transform(self.texts_vectors)
        
        plt.figure(figsize=(10, 10))
        plt.title("PCA representation of the data after vectoring with BERT", fontsize=15)
        plt.scatter(datapoint[:, 0], datapoint[:, 1], c=color, cmap='Set1' )
        plt.xlabel("PCA 1")
        plt.ylabel("PCA 2")
        plt.show()
