#    This file is part of NEORL.

#    Copyright (c) 2021 Exelon Corporation and MIT Nuclear Science and Engineering
#    NEORL is free software: you can redistribute it and/or modify
#    it under the terms of the MIT LICENSE

#    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#    SOFTWARE.

import numpy as np
import xarray as xr
import itertools
import random
import math
import inspect
import copy

from neorl import WOA
from neorl import GWO
from neorl import PSO
from neorl import MFO
from neorl import HHO
from neorl import DE
from neorl import ES

# Note: to incorporate additional algorithms into ensembles, the following needs to be done:
#     1. detect_algo needs to be updated to return appropriate name
#     2. clone_algo_obj needs to be updated to change the correct attribute in the dict
#     3. eval_algo_popnumber needs to be given some criteria for the minimum number of individuals
#        to run the evolution phase

def raj_logfact(n):
    """Ramanujan approximation of log(n!)"""
    f1 = n*np.log(n)
    f2 = -n
    f3 = np.log(n*(1+4*n*(1+2*n)))/6
    f4 = np.log(np.pi)/2
    return f1 + f2 + f3 + f4

def detect_algo(obj):
    #simple function to detect object type given neorl
    # algorithm object
    if isinstance(obj, WOA):
        return 'WOA'
    elif isinstance(obj, GWO):
        return 'GWO'
    elif isinstance(obj, PSO):
        return 'PSO'
    elif isinstance(obj, MFO):
        return 'MFO'
    elif isinstance(obj, HHO):
        return 'HHO'
    elif isinstance(obj, DE):
        return 'DE'
    elif isinstance(obj, ES):
        return 'ES'
    raise Exception('%s algorithm object not recognized or supported'%obj)

max_algos = ['PSO', 'DE', 'ES']#algos that change fitness function to make a maximum problem
min_algos = ['WOA', 'GWO', 'MFO', 'HHO']#algos that change fitness function to make a minimum problem

def wtd_remove(lst, ei, wts = None):
    #quick helper function to handle removing ei items from lst and returning them with
    #wts probability vector
    if wts is None:
        wts = [1/len(lst) for i in range(len(lst))]

    wts_sum = sum(wts)
    wts_checked = [a/wts_sum for a in wts] #correct for floating point errors

    #start here, caused by zeros in the weight
    indxs = np.random.choice(range(len(lst)), size=ei, p = wts_checked, replace = False)
    return [lst.pop(i) for i in reversed(sorted(indxs))], indxs

def clone_algo_obj(obj, nmembers, fit, bounds):
    # function to return a copy of an algorithm object with anumber of members given as
    # nmembers. This is to circumvent the error when the x0 passed in the evolute function
    # is a different size than the individuals given originally in the initialization of 
    # the algorithm object.
    # works for now, has potential of breaking

    def filter_kw(dftr, twk):
        sig = inspect.signature(twk)
        fks = [p.name for p in sig.parameters.values() if p.kind == p.POSITIONAL_OR_KEYWORD]
        fd = {fk:dftr[fk] for fk in fks if fk in dftr.keys()}
        return fd

    algo = detect_algo(obj)

    attrs = obj.__dict__

    if algo == 'WOA':
        attrs['nwhales'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return WOA(**filter_kw(attrs, WOA))
    elif algo == 'GWO':
        attrs['nwolves'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return GWO(**filter_kw(attrs, GWO))
    elif algo == 'PSO':
        attrs['npar'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return PSO(**filter_kw(attrs, PSO))
    elif algo == 'HHO':
        attrs['nhawks'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return HHO(**filter_kw(attrs, HHO))
    elif algo == 'DE':
        attrs['npop'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return DE(**filter_kw(attrs, DE))
    elif algo == 'ES':
        attrs['lambda_'] = nmembers
        attrs['fit'] = fit
        attrs['bounds'] = bounds
        return ES(**filter_kw(attrs, ES))

def get_algo_nmembers(obj):
    # function to retrieve the number of 'members' in the starting population of an
    # algorithm object plassed as obj

    algo = detect_algo(obj)

    if algo == 'WOA':
        return obj.nwhales
    elif algo == 'GWO':
        return obj.nwolves
    elif algo == 'PSO':
        return obj.npar
    elif algo == 'HHO':
        return obj.nhawks
    elif algo == 'DE':
        return obj.npop
    elif algo == 'ES':
        return obj.lambda_

def get_algo_ngtonevals(obj):
    # function to retrieve the number of function evaluations
    # for a given algo, args are num of generations and number of individuals, 
    # returns number of fxn evaluations
    algo = detect_algo(obj)

    if algo in ['WOA', 'GWO']:
        return lambda i, a : a*i
    elif algo == 'PSO':
        return lambda i, a : (i+1)*a
    elif algo == 'DE':
        return lambda i, a : 2*i*a
    elif algo == 'ES':
        return lambda i, a : (i+1)*a
    elif algo == 'HHO':
        print('--warning: HHO uses an upper bound for number of function evaluations,'
        ' be careful when using HHO with burdened variants')
        return lambda i, a : 2*i*a

def eval_algo_popnumber(obj, nmembers):
    # check if an algorithm is prepared to participate in evolution phase
    # based on its population information

    algo = detect_algo(obj)
    if algo in ['WOA', 'GWO', 'PSO', 'HHO', 'DE']:
        return nmembers >= 5
    elif algo == 'ES':
        return nmembers >= obj.mu

class Population:
    # Class to store information and functionality related to a single population
    # in the AEO algorithm. Should be characterized by an evolution strategy passed
    # as one of the optimization classes from the other algorithms in NEORL.
    def __init__(self, strategy, algo, init_pop, mode, conv = None):
        # strategy should be one of the optimization objects containing an "evolute" method
        # init_pop needs to match the population given to the strategy object initially
        # algo is string that identifies which class is being used
        # conv is a function which takes ngen and returns number of evaluations
        self.conv = conv
        self.strategy = copy.deepcopy(strategy)
        self.algo = algo
        self.members = init_pop
        self.n = len(self.members)
        self.mode = mode

        self.popname = '' #will be assigned externally after object has been initialized
                          #    used only for loggin purposes

        self.fitlog = []

    @property
    def fitness(self):
        return self.fitlog[-1]

    def evolute(self, ngen, fit, bounds, log): #fit is included to avoid needing to pull .fit methods
                                       #    from algo objects that may have been flipped
        #check if there are enouh members to evolve NOT appended to fitlog
        if not eval_algo_popnumber(self.strategy, len(self.members)):
            if len(self.fitlog) == 0:
                raise Exception("Starting population for %s too small for evoluation"%self.algo)
            fitness = self.fitness

        else:
            np.put(log['evolute'].data, [0], True)

            #update strategy with new population number
            self.strategy = clone_algo_obj(self.strategy, len(self.members), fit, bounds)

           #store last generation number
            self.last_ngen = ngen

            #perform evolution and store relevant information
            out = self.strategy.evolute(ngen, x0 = self.members)
            self.members = out[2]['last_pop'].iloc[:, :-1].values.tolist()
            self.member_fitnesses = out[2]['last_pop'].iloc[:, -1].values.tolist()

            if self.mode == 'max':
                self.fitlog.append(max(self.member_fitnesses))
            elif self.mode == 'min':
                self.fitlog.append(min(self.member_fitnesses))

            fitness = self.fitness

        #log relevant information
        if self.n != 0:
            log['member_x'][:self.n] = np.array(self.members).reshape(self.n, -1)
            log['member_fitnesses'][:self.n] = self.member_fitnesses
            np.put(log['nmembers'].data, [0],  [self.n])
            np.put(log['f'].data, [0], [self.fitness])
            if len(self.fitlog) > 1:
                np.put(log['delta_f'].data, [0], [self.fitlog[-1] - self.fitlog[-2]])

        return fitness

    def strength(self, g, g_burden, fmax, fmin, log, g_or_b):
        if self.mode == 'max':
            fbest, fworst = fmax, fmin
        elif self.mode == 'min':
            fworst, fbest = fmax, fmin

        #calculate strength for two different types
        if g == 'improve' and len(self.fitlog) > 1:
            unorm = max([self.fitlog[-1] - self.fitlog[-2], 0]) #in case best indiv got exported
        else: #when g == 'fitness' and also no matter what if on first cycle
            unorm = self.fitness

        #normalize strength measure
        normed = (unorm - fworst)/(fbest - fworst)

        if g_or_b == 'g':
            np.put(log['unburdened_g'].data, [0], [normed])
        elif g_or_b == 'b':
            np.put(log['unburdened_b'].data, [0], [normed])

        Nc = self.conv(self.last_ngen, self.n)
        #burden, if necessary
        if g_burden:
            normed /= 1 + Nc
            np.put(log['Nc'].data, [0], Nc)

        ret = normed

        if g_or_b == 'g':
            np.put(log['g'].data, [0], [ret])
        elif g_or_b == 'b':
            np.put(log['b'].data, [0], [ret])
        return ret

    def export(self, ei, wt, order, kf, gfrac, log):
        #decide what members to export and then remove them from members and return them
        if wt == 'uni': #uniform case very easy
            shuffled = list(range(len(self.members)))
            if self.n > 0:
                removed_x, removed_idcs =  wtd_remove(self.members, ei)
            else:
                removed_x, removed_idcs = [], []
            np.put(log['wb'].data, [0], [False])
            if self.n > 0:
                log['export_wts'][:self.n] = 1/self.n
        else:
            if order[0] == 'a': #handle the annealed cases
                if gfrac < 0.5:
                    o = order[1:]
                else:
                    o = order[2] + order[1]
            else: #if no annealing
                o = order

            #order the members and note how they are shuffled
            shuffled = list(range(len(self.members)))
            if (o == 'wb' and self.mode == 'max') \
                    or (o == 'bw' and self.mode == 'min'):
                self.members = [a for _, a in sorted(zip(self.member_fitnesses, self.members))]
                shuffled = [a for _, a in sorted(zip(self.member_fitnesses, shuffled))]
                self.member_fitnesses = sorted(self.member_fitnesses)
            if (o == 'bw' and self.mode == 'max') \
                    or (o == 'wb' and self.mode == 'min'):
                self.members = [a for _, a in sorted(zip(self.member_fitnesses, self.members), reverse = True)]
                shuffled = [a for _, a in sorted(zip(self.member_fitnesses, shuffled), reverse = True)]
                self.member_fitnesses = sorted(self.member_fitnesses, reverse = True)

            #calculate the wts
            seq = np.array(range(1, len(self.members) + 1))
            if wt == 'log':
                wts = (np.log(seq)+kf)/(self.n*kf + raj_logfact(self.n))
            elif wt == 'lin':
                wts = (seq-1+kf)/(self.n*(kf-.5)+.5*self.n**2)
            elif wt == 'exp':
                wts = (np.exp(seq-1) - 1 + kf)/((kf-1)*self.n+(1-np.exp(self.n))/(1-np.exp(1)))

            #log information
            np.put(log['wb'].data, [0], [o == 'wb'])
            log['export_wts'][:self.n][shuffled] = wts

            #draw members and return them
            if self.n > 0:
                removed_x, removed_idcs = wtd_remove(self.members, ei, wts)
            else:
                removed_x, removed_idcs = [], []

        np.put(log['exported'].data, [shuffled[j] for j in removed_idcs], [True]*len(removed_idcs))

        #remove member fitnesses to make sure len(members) == len(member_fitnesses)
        [self.member_fitnesses.pop(j) for j in reversed(sorted(removed_idcs))]

        self.n = len(self.members)

        #log which members were exported
        return removed_x

    def receive(self, individuals):
        #bring individuals into the populations
        self.members += individuals
        [self.member_fitnesses.append(np.nan) for i in individuals]
        self.n = len(self.members)


class AEO(object):
    """
    Animorphoc Ensemble Optimizer

    :param mode: (str) problem type, either "min" for minimization problem or "max" for maximization
    :param bounds: (dict) input parameter type and lower/upper bounds in dictionary form. Example: ``bounds={'x1': ['int', 1, 4], 'x2': ['float', 0.1, 0.8], 'x3': ['float', 2.2, 6.2]}``
    :param fit: (function) the fitness function
    :param optimizers: (list) list of optimizer instances to be included in the ensemble
    :param gen_per_cycle: (int) number of generations performed in evolution phase per cycle
    :param alpha: (float or str) option for exponent on g strength measure, if numeric, alpha is taken to be
        that value. If alpha is 'up' alpha is annealed from 0 to 1. If alpha is 'down' it is annealed from
        1 to 0.
    :param g: (str) either 'fitness' or 'improve' for strength measure for exportation number section of migration
    :param g_burden: (bool) True if strength if divided by number of fitness evaluations in evolution phase
    :param q: (float or str) option for favoring weak or strong pops in exportation number
    :param wt: (str) 'log', 'lin', 'exp', 'uni' for different weightings in member selection section of migration
    :param beta: (float or str) option for exponent on b strength measure. See alpha for details.
    :param b: (str) either 'fitness' or 'improve' for strength measure for destination selection section of migration
    :param b_burden: (bool) True if strength if divided by number of fitness evaluations in evolution phase
    :param ret: (bool) True if individual can return to original population in destination selection section
    :param order: (str) 'wb' for worst to best, 'bw' for best to worst, prepend 'a' for annealed starting in the given ordering.
    :param kf: (int) 0 or 1 for variant of weighting functions
    :param ncores: (int) number of parallel processors
    :param seed: (int) random seed for sampling
    """
    def __init__(self, mode, bounds, fit, 
            optimizers, gen_per_cycle,
            alpha, g, g_burden, q, wt,
            beta, b, b_burden, ret,
            order = None, kf = None,
            ncores = 1, seed = None):

        if not (seed is None):
            random.seed(seed)
            np.random.seed(seed)

        self.mode=mode
        self.fit = fit

        if mode == 'max': #create fit attribute to use for checking consistency of fits
            self.fitcheck=fit
        elif mode == 'min':
            def fitness_wrapper(*args, **kwargs):
                return -fit(*args, **kwargs)
            self.fitcheck=fitness_wrapper
        else:
            raise ValueError('--error: The mode entered by user is invalid, use either `min` or `max`')

        self.optimizers = optimizers
        self.algos = [detect_algo(o) for o in self.optimizers]
        self.gpc = gen_per_cycle

        self.bounds = bounds
        self.ncores = ncores

        #get functions to convert number of generations to number of evaluaions
        self.ngtonevals = [get_algo_ngtonevals(a) for a in self.optimizers]

        #infer variable types
        self.var_type = np.array([bounds[item][0] for item in bounds])

        self.dim = len(bounds)
        self.lb=[self.bounds[item][1] for item in self.bounds]
        self.ub=[self.bounds[item][2] for item in self.bounds]

        #check that all optimizers have options that match AEO
        self.ensure_consistency()

        #process variant options for exportation number
        self.alpha = alpha
        if (not isinstance(self.alpha, float) and
            not self.alpha in ['up', 'down']):
            raise Exception('invalid value for alpha, make sure it is a float!')
        if isinstance(self.alpha, float):
            if self.alpha < 0:
                raise Exception('alpha must be equal to or greater than 0')

        self.g = g
        if not self.g in ['fitness', 'improve']:
            raise Exception('invalid option for g')

        self.g_burden = g_burden
        if not isinstance(g_burden, bool):
            raise Exception('g_burden should be boolean type')

        self.q = q
        if (not isinstance(self.q, float)) and not self.q in ['up', 'down']:
            raise Exception('invalid value for q, make sure it is float or string option')

        #process variant options for member selection
        self.wt = wt
        if not self.wt in ['log', 'lin', 'exp', 'uni']:
            raise Exception('invalid option for wt')

        self.order = order
        if not self.order in ['wb', 'bw', 'awb', 'abw', None]:
            raise Exception('invalid option for order')

        self.kf = kf
        if not self.kf in [0, 1, None]:
            raise Exception('invalid option for kf')

        if self.wt == 'uni' and ((self.kf is not None)
                or (self.order is not None)):
            print('--warning: kf and order options ignored for uniform weighting')

        #process variant options for destination selection
        self.beta = beta
        if (not isinstance(self.beta, float) and
            not self.beta in ['up', 'down']):
            raise Exception('invalid value for beta, make sure it is a float!')
        if isinstance(self.beta, float):
            if self.beta < 0:
                raise Exception('beta must be equal to or greater than 0')

        self.b = b
        if not self.b in ['fitness', 'improve']:
            raise Exception('invalid option for b')

        self.b_burden = b_burden
        if not isinstance(b_burden, bool):
            raise Exception('b_burden should be boolean type')

        self.ret = ret
        if not isinstance(ret, bool):
            raise Exception('ret should be boolean type')

    def ensure_consistency(self):
        return #temp, may remove this function
        #loop through all optimizers and make sure all options are set to be the same
        gen_warning = ', check that options of all optimizers are the same as AEO'
        for o, a in zip(self.optimizers, self.algos):
            if a in max_algos:
                assert self.mode == o.mode,'%s has incorrect optimization mode'%o + gen_warning
                assert self.bounds == o.bounds,'%s has incorrect bounds'%o + gen_warning
                try:
                    assert self.fitcheck(self.lb) == o.fit(self.lb)
                    assert self.fitcheck(self.ub) == o.fit(self.ub)
                    inner_test = [np.random.uniform(self.lb[i], self.ub[i]) for i in range(len(self.ub))]
                    assert self.fitcheck(inner_test) == o.fit(inner_test)
                except:
                    raise Exception('i%s has incorrect fitness function'%o + gen_warning)
            else:
                assert self.mode == o.mode,'%s has incorrect optimization mode'%o + gen_warning
                assert self.bounds == o.bounds,'%s has incorrect bounds'%o + gen_warning
                try:
                    assert self.fitcheck(self.lb) == -o.fit(self.lb)
                    assert self.fitcheck(self.ub) == -o.fit(self.ub)
                    inner_test = [np.random.uniform(self.lb[i], self.ub[i]) for i in range(len(self.ub))]
                    assert self.fitcheck(inner_test) == -o.fit(inner_test)
                except:
                    raise Exception('i%s has incorrect fitness function'%o + gen_warning)

    def init_sample(self, bounds):
        indv=[]
        for key in bounds:
            if bounds[key][0] == 'int':
                indv.append(random.randint(bounds[key][1], bounds[key][2]))
            elif bounds[key][0] == 'float':
                indv.append(random.uniform(bounds[key][1], bounds[key][2]))
            else:
                raise Exception ('unknown data type is given, either int, float, or grid are allowed for parameter bounds')
        return indv

    def get_alphabeta(self, aorb, ncyc, Ncyc):
        if isinstance(aorb, float):
            return aorb
        elif aorb == 'up':
            return (ncyc-1)/(Ncyc-1)
        elif aorb == 'down':
            return 1 - (ncyc-1)/(Ncyc-1)

    def get_q(self, ncyc, Ncyc):
        if isinstance(self.q, float):
            return self.q
        elif self.q == "up":
            return 2/(1 - Ncyc)*(1 - ncyc)-1
        elif self.q == "down":
            return 2/(1 - Ncyc)*(ncyc - 1)+1


    def evolute(self, Ncyc, npop0 = None, x0 = None, pop0 = None, stop_criteria = None, verbose = False):
        """
        This function evolutes the AEO algorithm for a number of cycles. Either
        npop0 or x0 and pop0 are required.

        :param Ncyc: (int) number of cycles to evolute
        :param pop0: (list of ints) number of individuals in starting population for each optimizer
        :param x0: (list of lists) initial positions of individuals in problem space
        :param pop0: (list of ints) population assignments for x0, integer corresponding to assigned population ordered
            according to self.optimize
        "param stop_criteria: (None or callable) function which returns condition if evolution should continue, can be
            used to stop evolution at certain number of function evaluations
        """
        #if npop0, x0 and pop0 are none, detect populations from algos
        if npop0 is None and x0 is None and pop0 is None:
            npop0 = [get_algo_nmembers(a) for a in self.optimizers]
        #intepret npop0 or x0 and pop0 input
        if x0 is not None:
            if npop0 is not None:
                print('--warning: x0 and npop0 is defined, ignoring npop0')
            assert len(x0) == len(pop0), 'x0 and pop0 must be ov equal length'
        else:
            x0 = [self.init_sample(self.bounds) for i in range(sum(npop0))]
            dup = [[i]*npop0[i] for i in range(len(npop0))]
            pop0 = list(itertools.chain.from_iterable(dup))

        #separate starting positions according to optimizer/strategy, initialize Population objs
        self.pops = []
        for i in range(len(self.optimizers)):
            xpop = []
            for x, p in zip(x0, pop0):
                if p == i:
                    xpop.append(x)
            self.pops.append(Population(self.optimizers[i], self.algos[i],
                    xpop, self.mode, self.ngtonevals[i]))

        #initialize log Dataset
        membercoords = range(len(x0))
        cyclecoords = range(1, Ncyc + 1)
        popcoords = []
        for p in self.pops:
            algo = p.algo
            if not (algo in popcoords):
                p.popname = algo
                popcoords.append(p.popname)
            else:
                i = 2
                while algo + str(i).zfill(3) in popcoords:
                    i += 1
                p.popname = algo + str(i).zfill(3)
                popcoords.append(p.popname)

        varcoords = list(self.bounds.keys())

        nm = len(membercoords)
        nc = len(cyclecoords)
        npp = len(popcoords)
        nv = len(varcoords)



        log = xr.Dataset(
                {
                    'initial_member_x'   : (['member', 'pop',          'var'], np.zeros((nm, npp,     nv), dtype = np.float64)),
                    'member_x'           : (['member', 'pop', 'cycle', 'var'], np.zeros((nm, npp, nc, nv), dtype = np.float64)),
                    'nmembers'           : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.int32)),
                    'member_fitnesses'   : (['member', 'pop', 'cycle'], np.zeros((nm, npp, nc), dtype = np.float64)),
                    'nexport'            : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.int32)),
                    'export_str_scaled'  : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'export_pop_wts'     : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'alpha'              : ([                 'cycle'], np.zeros(          nc , dtype = np.float64)),
                    'wb'                 : ([                 'cycle'], np.zeros(          nc , dtype = np.bool8)),
                    'g'                  : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'f'                  : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'unburdened_g'       : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'Nc'                 : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.int32)),
                    'delta_f'            : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'fmin'               : ([                 'cycle'], np.zeros(          nc , dtype = np.float64)),
                    'fmax'               : ([                 'cycle'], np.zeros(          nc , dtype = np.float64)),
                    'migration'          : ([                 'cycle'], np.zeros(          nc , dtype = np.bool8)),
                    'export_wts'         : (['member', 'pop', 'cycle'], np.zeros((nm, npp, nc), dtype = np.float64)),
                    'exported'           : (['member', 'pop', 'cycle'], np.zeros((nm, npp, nc), dtype = np.bool8)),
#                    'pop_after_migrate'  : (['member', 'pop', 'cycle'], np.zeros((nm, npp, nc), dtype = '<U6')),
                    'beta'               : ([                 'cycle'], np.zeros(          nc , dtype = np.float64)),
                    'b'                  : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'unburdened_b'       : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.float64)),
                    'A'                  : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.int32)),
                    'evolute'            : ([          'pop', 'cycle'], np.zeros((    npp, nc), dtype = np.bool8))},
                coords = {
                    'member'  : membercoords,
                    'pop'     : popcoords,
                    'cycle'   : cyclecoords,
                    'var'     : varcoords},
                attrs = {"Ncycles" : 0}
                )
        #initial_member_x: positions of all individuals in a population before any evolution
        #member_x: positions of members in each population as through each cycle
        #nmembers: number of members in each population in each cycle
        #export_str_scaled: scaled strengths of each population each cycle
        #export_pop_wts: weights passed into binomial function for ei selection
        #alpha: alpha parameter as it may change over each cycle
        #wb: ordering of individuals within the populations when used for member selection
        #g: unscaled strengths of each population each cycle
        #f: fitness of each population each cycle, may have existed across previous cycles
        #unburdened_g: unscaled strengths of each pop each cycle without the burden applied
        #Nc: Number of function evaluations required to get the f variable associated with that cycle
        #delta_f: difference in current cycle fitness to previous cycle fitness
        #fmin: minimum fitness across all populations for a single cycle
        #fmax: maximum fitness across all populations for a single cycle
        #migration: bool as to whether or not migration is performed, if fmax=fmix, no evolution
        #export_wts: weights used for each individual in the member selection phase
        #exported: boolean as to whether or not an individual was exported
        #beta: beta parameter as it may change over each cycle
        #b: unscaled strengths of each population for the destination selection phase
        #unburdened_b: unscaled strengths without burdened applied for member selection phase
        #A: number of members from export pool that end up in a particulat population each cycle
        #evolute: is whether or not that population was evoluted each cycle



        #log positions of initial members
        for p in self.pops:
            log['initial_member_x'].loc[{'pop' : p.popname}][:len(p.members)] = p.members

        #perform evolution/migration cycle
        for i in range(1, Ncyc + 1):
            #evolution phase
            pop_fits = [p.evolute(self.gpc, self.fit, self.bounds, log.loc[{'pop' : p.popname, 'cycle' : i}]) for p in self.pops]

            #exportation number
            #  calc weights
            maxf = max(pop_fits)
            minf = min(pop_fits)
            if maxf == minf:#export nobody if this true
                eis = [0]*len(self.pops)
                log['migration'].loc[{'cycle' : i}] = False
            else:
                alpha = self.get_alphabeta(self.alpha, i, Ncyc)
                strengths_exp = [p.strength(self.g, self.g_burden, maxf, minf, log.loc[{'pop' : p.popname, 'cycle' : i}], 'g')**alpha for p in self.pops]
                strengths_exp_scaled = [s/sum(strengths_exp) for s in strengths_exp]

                #  sample binomial to get e_i for each population
                qt = self.get_q(i, Ncyc)
                binomial_wts = [(.5 - s)*qt + .5 for s in strengths_exp_scaled]
                eis = [np.random.binomial(len(p.members), binomial_wts[j]) for j, p in enumerate(self.pops)]
                log['migration'].loc[{'cycle' : i}] = True

                log['export_str_scaled'].loc[{'cycle' : i}] = strengths_exp_scaled
                log['export_pop_wts'].loc[{'cycle' : i}] = binomial_wts

            # log pop export info
            log['nexport'].loc[{'cycle' : i}] = eis
            log['fmax'].loc[{'cycle' : i}] = maxf
            log['fmin'].loc[{'cycle' : i}] = minf
            log['alpha'].loc[{'cycle' : i}] = alpha

            #member selection
            #  members removed from population with this export method
            exported = [p.export(eis[j], self.wt, self.order, self.kf, i/Ncyc, log.loc[{'pop' : p.popname, 'cycle' : i}]) for j, p in enumerate(self.pops)]

            #destination selection
            beta = self.get_alphabeta(self.beta, i, Ncyc)
            log['beta'].loc[{'cycle' : i}] = beta

            if maxf == minf: #doesn't matter because nobody is exported
                strengths_dest = [1.]*len(self.pops)
            else:
                strengths_dest = [p.strength(self.b, self.b_burden, maxf, minf, log.loc[{'pop' : p.popname, 'cycle' : i}], 'b')**beta for p in self.pops]


            if self.ret:#if population can return to original population
                #manage members that are currently without a home
                exported = list(itertools.chain.from_iterable(exported))
                random.shuffle(exported)#in-place randomize order

                #calculate normalized probabilities and draw samples
                strengths_dest_scaled = [s/sum(strengths_dest) for s in strengths_dest]
                allotments = np.random.multinomial(len(exported), strengths_dest_scaled)
                log['A'].loc[{'cycle' : i}] = allotments

                #distribute individuals according to the sample
                for a, p in zip(allotments, self.pops):
                    p.receive(exported[:a])
                    exported = exported[a:]

            else:
                pop_indxs = list(range(len(self.pops)))
                allotment_holder = np.zeros(len(self.pops))
                for j, exported_group in enumerate(exported):
                    strengths_inotj = strengths_dest[:j] + strengths_dest[j+1:]
                    strengths_inotj_scaled = [s/sum(strengths_inotj) for s in strengths_inotj]
                    pop_indxs_inotj = pop_indxs[:j] + pop_indxs[j+1:]
                    random.shuffle(exported_group)
                    allotment = np.random.multinomial(len(exported_group), strengths_inotj_scaled)
                    for a, pi in zip(allotment, pop_indxs_inotj):
                        self.pops[pi].receive(exported_group[:a])
                        exported_group = exported_group[a:]
                    allotment_holder[pop_indxs_inotj] += allotment

                log['A'].loc[{'cycle' : i}] = allotment_holder

            #check if desired number of function evaluations has been reached
            log.attrs["Ncycles"] = i
            if not stop_criteria is None:
                if stop_criteria() == True:
                    break

        return log



    #TODO: Markov Matrix calculation
    #TODO: Ramanujan approx for log(x!)
    #TODO: Fitness checker outside of consistency method


