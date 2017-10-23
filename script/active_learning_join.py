
import sys
import os

import numpy
import numpy as np
import h5py
import shelve
import sqlite3
import random

import pylab

from keras.layers import Dense, Activation
from keras.models import Sequential
from keras.callbacks import EarlyStopping

from synth_halfphone import Synthesiser
from train_halfphone import get_data_dump_name

class JoinDatabaseForActiveLearning(Synthesiser):
    def __init__(self, config_file):
        super(JoinDatabaseForActiveLearning, self).__init__(config_file)
        
        join_data_dump = get_data_dump_name(self.config, joindata=True)
        join_data_sql_fname = get_data_dump_name(self.config, joinsql=True)

        if not os.path.isfile(join_data_dump):
            sys.exit('Join data file %s does not exist -- try setting dump_join_data to True in config and rerunning train_halfphone.py')

        f = h5py.File(join_data_dump, "r")
        self.start_join_feats = f["start_join_feats"][:,:]
        self.end_join_feats = f["end_join_feats"][:,:]    
        f.close()

        self.setup_join_database(join_data_sql_fname)  # creates self.connection & self.cursor
        

        ## get seed set:
        nseed = 3
        self.cursor.execute("SELECT from_index, to_index FROM transitions ORDER BY RANDOM() LIMIT %s"%(nseed)) 
        seedset = self.cursor.fetchall()

        print seedset
        self.cursor.execute("SELECT from_index, to_index FROM transitions ORDER BY RANDOM() LIMIT %s"%(nseed)) 
        seedset = self.cursor.fetchall()


        self.judgement_classes = ['good','bad']
        self.class_dict = dict([(thing[0], thing) for thing in self.judgement_classes])
        assert len(self.class_dict) == len(self.judgement_classes), 'Please use unique starting letters for judgement_classes'

        print dir(self)
        user_judgements = self.present_candidate_joins_single_foreign_unit(seedset)

        print user_judgements

        print seedset





        sys.exit('stop before autoencoder stuff')


        natural_junctures = self.get_natural_junctures()
        self.train_autoencoder(natural_junctures, max_epoch=3) ## creates self.autoencoder

        natural_scores = self.get_prediction_errors(natural_junctures)


        fake_scores = []
        for i in xrange(self.number_of_units):
            if i % 100 == 0:
                print i
            self.cursor.execute("SELECT to_index FROM transitions WHERE from_index=%s"%(i)) 
            to_index = self.cursor.fetchall()
            #print to_index
            to_index = np.array(to_index, dtype=int).flatten()
            #print to_index

            ## Remove natural transitions:- TODO: in SQL
            to_index = to_index[to_index!=i+1]

            from_ixx = np.ones(to_index.shape, dtype=int) * i
            features = np.hstack([self.end_join_feats[from_ixx,:], self.start_join_feats[to_index,:]])
            fake_scores.append(self.get_prediction_errors(features))

        fake_scores = np.concatenate(fake_scores)

        #pylab.subplot(211)
        pylab.hist(natural_scores, bins=30, alpha=0.6, color='g', normed=1)

        #pylab.subplot(212)
        pylab.hist(fake_scores, bins=30, alpha=0.6, color='b', normed=1)

        pylab.show()






        sys.exit('sdvsfbv')


        print natural_scores


        unit_seq = self.sample_uniform_a(nsteps=800)
        self.concatenate(unit_seq, '/tmp/out.wav')
        

    def present_candidate_joins_nonsense(self, index_pairs):
        CONTEXT = 20
        judgements = []
        for (fro, to) in index_pairs:
            start = max(0, fro - CONTEXT)
            end = min(self.number_of_units, to + CONTEXT)
            self.concatenate(range(start, fro) + range(to, end), '/tmp/join_%s_%s.wav'%(fro, to))
            judgements.append(self.present_audio_instance('/tmp/join_%s_%s.wav'%(fro, to)))
        return judgements

    def present_candidate_joins_single_foreign_unit(self, index_pairs):
        CONTEXT = 20
        judgements = []
        for (fro, to) in index_pairs:
            print fro, to
            start = max(0, fro - CONTEXT)
            end = min(self.number_of_units, fro + CONTEXT + 1)
            insert_point = CONTEXT + 1
            if fro - CONTEXT < 0:
                insert_point += fro - CONTEXT
                print 'CORRETION!!!!!!!!!! ---------------'
            unit_sequence = range(start, end)
            self.concatenate(unit_sequence, '/tmp/join_%s_%s_nat.wav'%(fro, to))
            unit_sequence[insert_point] = to
            print unit_sequence

            print 'try replacing %s with %s'%(self.train_unit_names[fro + 1], self.train_unit_names[to])
            
            self.concatenate(unit_sequence, '/tmp/join_%s_%s.wav'%(fro, to))

            judgements.append(self.present_audio_instance('/tmp/join_%s_%s.wav'%(fro, to), natural_reference='/tmp/join_%s_%s_nat.wav'%(fro, to)))
        return judgements


    def make_prompt(self, audio_prompt=False, natural_reference=None):
        prompt = ["%s for %s, "%(code, category) for (code, category) in self.class_dict.items()] 
        prompt = " ".join(prompt)
        prompt = "  Type: " + prompt
        if audio_prompt:
            prompt += " (or r to replay)"
        if natural_reference:
            prompt += " (or n to play natural reference)"
        prompt += " ... "
        return prompt


    def present_audio_instance(self, fname, natural_reference=None):  

        assert os.path.isfile(fname) and fname.endswith('.wav') 

        print "  Please listen to this example:"
        os.system("play " + fname)
        prompt = self.make_prompt(audio_prompt=True, natural_reference=natural_reference)
        valid_response_received = False
        while not valid_response_received:       
            raw_reponse = raw_input(prompt)
            print 
            print "  ------------------------------"
            print 
            if raw_reponse=="r":
                os.system("play " + fname)
            if natural_reference:
                if raw_reponse == 'n':
                    os.system("play " + natural_reference)
            if raw_reponse in self.class_dict:
                valid_response_received=raw_reponse
        return self.class_dict[valid_response_received]

    def get_natural_junctures(self):
        '''
        TODO: exclude joins between sentences
        '''
        return np.hstack([self.end_join_feats[:-1,:], self.start_join_feats[1:,:]])


    def sample_uniform_a(self, nsteps=100):
        '''
        draw from all transitions given by basic linguistic constraints only (allowing natural)
        '''
        ## assemble list of unit indices from which to synthesise:
        sampled = [random.randint(0, self.number_of_units)]
        while len(sampled) < nsteps:
            self.cursor.execute("SELECT to_index FROM transitions WHERE from_index=%s"%(sampled[-1])) 
            #print("\nfetch one:")
            res = self.cursor.fetchall()
            ## TODO: move random selection to sql call (https://stackoverflow.com/questions/2279706/select-random-row-from-an-sqlite-table)
            
            sel = random.choice(res)[0]
            sampled.append(sel)            

        return sampled

            


    def get_prediction_errors(self, data):
        predictions = self.autoencoder.predict(data)
        sq_errs = (predictions - data)**2
        scores = sq_errs.mean(axis=1)    
        return scores




    def train_autoencoder(self, data, max_epoch=30):

        
        m,n = data.shape

        model = Sequential()

        model.add(Dense(units=1000, input_dim=n))
        model.add(Activation('relu'))
        model.add(Dense(units=1000))
        model.add(Activation('relu'))

        model.add(Dense(units=60))
    #    model.add(Activation('relu'))

        model.add(Dense(units=1000))
        model.add(Activation('relu'))
        model.add(Dense(units=n))

        model.compile(loss='mean_squared_error', optimizer='adam')

        earlyStopping = EarlyStopping(monitor='val_loss', patience=5, verbose=1, mode='min')

        model.fit(data, data, epochs=max_epoch, batch_size=64, callbacks=[earlyStopping], validation_split=0.10, shuffle=True)

        self.autoencoder = model

        ## TODO: save model to disk



    def index_units_by_left_phone(self):
        ### Build index of units by l phone only (c phones are already handled by synth.unit_index):
        print 'build l index...'
        l_index = {}
        seen = {}
        for ll_l_c_r_rr in self.train_unit_names:
            (ll,l,c,r,rr) = ll_l_c_r_rr.split('/')
            if c.endswith('_L'):
                #assert '%s/%s'%(l,c) not in l_index
                if '%s/%s'%(l,c) not in seen:
                    seen['%s/%s'%(l,c)] = 0
                    if l not in l_index:
                        l_index[l] = []
                    l_index[l].extend(self.unit_index['%s/%s'%(l,c)])
        print '...done'
        return l_index


    def setup_join_database(self, fname):

        if os.path.isfile(fname):
            self.connection = sqlite3.connect(fname) # ("/tmp/transitions.db")
            self.cursor = self.connection.cursor()
            print '------'            
            print 'sql file already exists -- assume database has been made' ## TODO: aactually check table within file
            print fname
            print '------'
            return      
        ## else continue to create the data base      

        ## determine candidate joins:
        ## Work out the minimal linguistic criteria which should signal a possible join.
        l_index = self.index_units_by_left_phone()

        #transitions = [] ## list of lists
        #transitions = shelve.open('/tmp/transitions')


        self.connection = sqlite3.connect(fname) # ("/tmp/transitions.db")
        self.cursor = self.connection.cursor()

        ## TODO: number of votes? annotator? time? fatigue? recently challenged?
        sql_command = """
        CREATE TABLE transitions ( 
        from_index INTEGER, 
        to_index INTEGER, 
        natural BOOLEAN, 
        labelled BOOLEAN, 
        labelled_ok BOOLEAN,
        trained_on BOOLEAN,
        confidence FLOAT);"""

        self.cursor.execute(sql_command)   
   


        nlinks = 0 # count number of possibles
        for (i,name) in enumerate(self.train_unit_names):
            if i % 100 == 0:
                print '%s of %s'%(i, self.number_of_units)
            (ll,l,c,r,rr) = name.split('/')
            if c.endswith('_L'):
                next_unit = c.replace('_L','_R')
                #transitions.append(self.unit_index[next_unit])
                transitions_from_here = self.unit_index[next_unit]  
            else:
                ## find all following units compatible with it:
                this_current = c.split('_')[0]
                this_right = r
                transitions_from_here = l_index.get(this_current, [])  +   self.unit_index.get(this_right + '_L', []) 


                # for (l,c) in lc_inventory:
                #     if this_current == l or this_right == c:
                #         next_unit = '%s/%s_L'%(l,c)
                #         #print '%s %s   %s'%(this_current, this_right, next_unit)
                #         transitions_from_here.extend(self.unit_index[next_unit])


                #transitions.append(transitions_from_here)

            ### add to database:
            for j in transitions_from_here:

                natural = False
                if j == i+1:
                    natural = True
                format_str = """INSERT INTO transitions (from_index, to_index, natural, labelled, labelled_ok, trained_on, confidence)
                VALUES ("{from_index}", "{to_index}", "{natural}", "{labelled}", "{labelled_ok}", "{trained_on}", "{confidence}");"""

                sql_command = format_str.format(from_index=i, to_index=j, natural=natural,\
                                                 labelled=False, labelled_ok=False, trained_on=False, \
                                                 confidence=0.5)
                self.cursor.execute(sql_command)

            self.connection.commit()
            nlinks += len(transitions_from_here)




    def junk():

        #print transitions
        #print transitions['101']
        #nlinks = sum([len(sublist) for sublist in transitions])


        cursor.execute("SELECT * FROM transitions") 
        print("fetchall:")
        result = cursor.fetchall() 
        for r in result:
            print(r)
        cursor.execute("SELECT * FROM transitions") 
        print("\nfetch one:")
        res = cursor.fetchone() 
        print(res)
        print '----'

        print nlinks
        print self.number_of_units
        print 'done'

        connection.close()

        sys.exit('evaeveb1111')  

    def determine_candidate_joins_SHELVE(self):


        ## Work out the minimal linguistic criteria which should signal a possible join.
        l_index = self.index_units_by_left_phone()

        #transitions = [] ## list of lists
        transitions = shelve.open('/tmp/transitions')

        nlinks = 0 # count number of possibles
        for (i,name) in enumerate(self.train_unit_names):
            if i % 100 == 0:
                print '%s of %s'%(i, self.number_of_units)
            (ll,l,c,r,rr) = name.split('/')
            if c.endswith('_L'):
                next_unit = c.replace('_L','_R')
                #transitions.append(self.unit_index[next_unit])
                transitions_from_here = self.unit_index[next_unit]
                
            else:
                ## find all following units compatible with it:
                this_current = c.split('_')[0]
                this_right = r
                transitions_from_here = l_index.get(this_current, [])  +   self.unit_index.get(this_right + '_L', []) 


                # for (l,c) in lc_inventory:
                #     if this_current == l or this_right == c:
                #         next_unit = '%s/%s_L'%(l,c)
                #         #print '%s %s   %s'%(this_current, this_right, next_unit)
                #         transitions_from_here.extend(self.unit_index[next_unit])


                #transitions.append(transitions_from_here)
            



            transitions[str(i)] = numpy.array(transitions_from_here, dtype=int)
            nlinks += len(transitions_from_here)

        #print transitions
        print transitions['101']
        #nlinks = sum([len(sublist) for sublist in transitions])
        print nlinks
        print self.number_of_units
        print 'done'