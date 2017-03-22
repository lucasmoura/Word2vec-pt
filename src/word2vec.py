import numpy as np
import os
import random
import tensorflow as tf
from tensorflow.contrib.tensorboard.plugins import projector
import time
import util
from datareader import DataReader


class Config(object):
    """
    Holds model hyperparams and data information.
    The config class is used to store various hyperparameters and dataset
    information parameters. Model objects are passed a Config() object at
    instantiation.
    """
    def __init__(self,
                 vocab_size=50000,
                 batch_size=128,
                 embed_size=128,
                 skip_window=1,
                 num_skips=2,
                 num_sampled=64,
                 lr=1.0,
                 num_steps=100001,
                 show_step=2000,
                 verbose_step=10000,
                 valid_size=16,
                 valid_window=100):
        self.vocab_size = vocab_size
        self.batch_size = batch_size
        self.embed_size = embed_size
        self.skip_window = skip_window
        self.num_skips = num_skips
        self.num_sampled = num_sampled
        self.lr = lr
        self.num_steps = num_steps
        self.show_step = show_step
        self.verbose_step = verbose_step
        self.valid_size = valid_size
        self.valid_window = valid_window
        self.valid_examples = np.array(random.sample(range(self.valid_window),
                                                     self.valid_size))


class SkipGramModel:
    """
    Build the graph for word2vec model
    """
    def __init__(self, config):
        self.logdir = util.newlogname()
        self.config = config
        self.vocab_size = self.config.vocab_size
        self.embed_size = self.config.embed_size
        self.batch_size = self.config.batch_size
        self.num_sampled = self.config.num_sampled
        self.lr = self.config.lr
        self.valid_examples = self.config.valid_examples
        self.build_graph()

    def create_placeholders(self):
            """
            Creat placeholder for the models graph
            """
            with tf.name_scope("words"):
                self.center_words = tf.placeholder(tf.int32,
                                                   shape=[self.batch_size],
                                                   name='center_words')
                self.targets = tf.placeholder(tf.int32,
                                              shape=[self.batch_size, 1],
                                              name='target_words')
                self.valid_dataset = tf.constant(self.valid_examples,
                                                 dtype=tf.int32)

    def create_weights(self):
        """
        Creat all the weights and bias for the models graph
        """
        emshape = (self.vocab_size, self.embed_size)
        eminit = tf.random_uniform(emshape, -1.0, 1.0)
        self.embeddings = tf.Variable(eminit, name="embeddings")

        with tf.name_scope("softmax"):
                    Wshape = (self.vocab_size, self.embed_size)
                    bshape = (self.vocab_size)
                    std = 1.0/(self.config.embed_size ** 0.5)
                    Winit = tf.truncated_normal(Wshape, stddev=std)
                    binit = tf.zeros(bshape)
                    self.weights = tf.get_variable("weights",
                                                   dtype=tf.float32,
                                                   initializer=Winit)
                    self.biases = tf.get_variable("biases",
                                                  dtype=tf.float32,
                                                  initializer=binit)

    def create_loss(self):
        with tf.name_scope("loss"):
            self.embed = tf.nn.embedding_lookup(self.embeddings,
                                                self.center_words,
                                                name='embed')
            self.loss = tf.reduce_mean(tf.nn.sampled_softmax_loss(self.weights,
                                                                  self.biases,
                                                                  self.targets,
                                                                  self.embed,
                                                                  self.num_sampled,
                                                                  self.vocab_size))

    def create_optimizer(self):
        with tf.name_scope("train"):
            opt = tf.train.AdagradOptimizer(self.lr)
            self.optimizer = opt.minimize(self.loss)

    def create_valid(self):
        norm = tf.sqrt(tf.reduce_sum(tf.square(self.embeddings),
                                     1, keep_dims=True))
        self.normalized_embeddings = self.embeddings / norm
        valid_embeddings = tf.nn.embedding_lookup(self.normalized_embeddings,
                                                  self.valid_dataset)
        self.similarity = tf.matmul(valid_embeddings,
                                    tf.transpose(self.normalized_embeddings))

    def create_summaries(self):
        with tf.name_scope("summaries"):
            tf.summary.scalar("loss", self.loss)
            self.summary_op = tf.summary.merge_all()

    def build_graph(self):
            """
            Build the graph for our model
            """
            self.graph = tf.Graph()
            with self.graph.as_default():
                self.create_placeholders()
                self.create_weights()
                self.create_loss()
                self.create_optimizer()
                self.create_valid()
                self.create_summaries()


def run_training(model, data, verbose=True, visualization=True, Debug=False):
    logdir = model.logdir
    batch_size = model.config.batch_size
    num_skips = model.config.num_skips
    skip_window = model.config.skip_window
    valid_examples = model.config.valid_examples
    num_steps = model.config.num_steps
    show_step = model.config.show_step
    verbose_step = model.config.verbose_step
    data_index = 0
    with tf.Session(graph=model.graph) as session:
        tf.global_variables_initializer().run()
        ts = time.time()
        print("Initialized")
        if visualization:
            print("\n&&&&&&&&& For TensorBoard visualization type &&&&&&&&&&&")
            print("\ntensorboard  --logdir={}\n".format(logdir))
            print("\n&&&&&&&&& And for the 3d embedding visualization type &&")
            print("\ntensorboard  --logdir=./processed\n")
        average_loss = 0
        total_loss = 0
        if visualization:
            writer = tf.summary.FileWriter(logdir, session.graph)
        for step in range(num_steps):
            data_index, batch_data, batch_labels = data.batch_generator(batch_size,
                                                                        num_skips,
                                                                        skip_window,
                                                                        data_index)
            feed_dict = {model.center_words: batch_data,
                         model.targets: batch_labels}
            _, l, summary = session.run([model.optimizer,
                                         model.loss,
                                         model.summary_op],
                                        feed_dict=feed_dict)
            average_loss += l
            total_loss += l
            if visualization:
                writer.add_summary(summary, global_step=step)
                writer.flush()
            if step % show_step == 0:
                if step > 0:
                    average_loss = average_loss / show_step
                    print("Average loss at step", step, ":", average_loss)
                    average_loss = 0
            if step % verbose_step == 0 and verbose:
                sim = model.similarity.eval()
                for i in range(model.config.valid_size):
                    valid_word = data.index2word[valid_examples[i]]
                    top_k = 8  # number of nearest neighbors
                    nearest = (-sim[i, :]).argsort()[1:top_k+1]
                    log = "Nearest to %s:" % valid_word
                    for k in range(top_k):
                        close_word = data.index2word[nearest[k]]
                        log = "%s %s," % (log, close_word)
                    print(log)

        final_embeddings = model.normalized_embeddings.eval()
        if visualization:
            # it has to variable. constants don't work here.
            embedding_var = tf.Variable(final_embeddings[:1000],
                                        name='embedding')
            session.run(embedding_var.initializer)

            emconfig = projector.ProjectorConfig()
            summary_writer = tf.summary.FileWriter('processed')

            # add embedding to the config file
            embedding = emconfig.embeddings.add()
            embedding.tensor_name = embedding_var.name

            # link this tensor to its metadata file,
            # in this case the first 1000 words of vocab
            embedding.metadata_path = 'processed/vocab_1000.tsv'

            # saves a configuration file that
            # TensorBoard will read during startup.
            projector.visualize_embeddings(summary_writer, emconfig)
            saver_embed = tf.train.Saver([embedding_var])
            saver_embed.save(session, 'processed/model3.ckpt', 1)

    te = time.time()
    if Debug:
        return te-ts, total_loss/num_steps
    else:
        return final_embeddings

if __name__ == "__main__":
    import pickle
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("-f",
                        "--file",
                        type=str,
                        default='basic',
                        help="""text file to apply
                        the model (default=basic_pt.txt)""")

    parser.add_argument("-s",
                        "--num_steps",
                        type=int,
                        default=100000,
                        help="number of training steps (default=100000)")

    parser.add_argument("-v",
                        "--vocab_size",
                        type=int,
                        default=50000,
                        help="vocab size (default=50000)")

    parser.add_argument("-b",
                        "--batch_size",
                        type=int,
                        default=128,
                        help="batch size (default=128)")

    parser.add_argument("-e",
                        "--embed_size",
                        type=int,
                        default=128,
                        help="embeddings size (default=128)")

    parser.add_argument("-k",
                        "--skip_window",
                        type=int,
                        default=1,
                        help="skip window (default=1)")

    parser.add_argument("-n",
                        "--num_skips",
                        type=int,
                        default=2,
                        help="""number of skips, number of times
                        a center word will be re-used (default=2)""")

    parser.add_argument("-S",
                        "--num_sampled",
                        type=int,
                        default=64,
                        help="number of negativ samples(default=64)")

    parser.add_argument("-l",
                        "--learning_rate",
                        type=float,
                        default=1.0,
                        help="learning rate (default=1.0)")

    parser.add_argument("-w",
                        "--show_step",
                        type=int,
                        default=2000,
                        help="""show result in multiples
                        of this step (default=2000)""")

    parser.add_argument("-B",
                        "--verbose_step",
                        type=int,
                        default=10000,
                        help="""show similar words in
                        multiples of this step (default=10000)""")

    parser.add_argument("-V",
                        "--valid_size",
                        type=int,
                        default=16,
                        help="""number of words to
                        display similarity(default=16)""")

    parser.add_argument("-W",
                        "--valid_window",
                        type=int,
                        default=100,
                        help="""number of words to from vocab to
                        choose the words to display similarity(default=100)""")

    args = parser.parse_args()
    file_path = args.file
    if file_path == 'basic':
        file_path = util.get_path_basic_corpus()
        args.vocab_size = 500
        print(args.vocab_size)

    config = Config(vocab_size=args.vocab_size,
                    batch_size=args.batch_size,
                    embed_size=args.embed_size,
                    skip_window=args.skip_window,
                    num_skips=args.num_skips,
                    num_sampled=args.num_sampled,
                    lr=args.learning_rate,
                    num_steps=args.num_steps,
                    show_step=args.show_step,
                    verbose_step=args.verbose_step,
                    valid_size=args.valid_size,
                    valid_window=args.valid_window)

    currentdir = os.path.dirname(__file__)
    my_data = DataReader(file_path)
    my_data.get_data(args.vocab_size)

    process_dir = 'processed/'
    if not os.path.exists(process_dir):
        os.makedirs(process_dir)
    old_vocab_path = os.path.join(currentdir, 'vocab_1000.tsv')
    new_vocab_path = os.path.join(currentdir, 'processed')
    new_vocab_path = os.path.join(new_vocab_path, 'vocab_1000.tsv')
    os.rename(old_vocab_path, new_vocab_path)

    my_model = SkipGramModel(config)
    embeddings = run_training(my_model, my_data)

    pickle_dir = 'pickles/'
    if not os.path.exists(pickle_dir):
        os.makedirs(pickle_dir)
    inverse = file_path[::-1][4:]
    number = -1
    for i, char in enumerate(inverse):
        if char == "/":
            number = i
            break
    if number == -1:
        filename = inverse[::-1] + '.pickle'
    else:
        filename = inverse[:number][::-1] + '.pickle'

    prefix = os.path.join(currentdir, 'pickles')
    filename = os.path.join(prefix, filename)

    f = open(filename, 'wb')
    di = {'word2index': my_data.word2index,
          'index2word': my_data.index2word,
          'embeddings': embeddings}
    pickle.dump(di, f)
    f.close()

    print("\n==========================================")
    print("""\nThe pickle file with the word embeddings can be found in the folder 'pickles'.
    \nThe pickle stores a dict with:
    \ni) a dict of words to indexes ('word2index')
    \nii) a dict of indexes to words  ('index2word')
    \niii) an array of shape (vocab_size,embed_size) ('embeddings')""")