import numpy as np
from intentcart.learning import choose_pair, posterior, sigmoid, PARTICLES

def test_value_of_information_matches_explicit_two_branch_calculation():
    u=np.array([[.9,.3,.6],[.2,.8,.5],[.6,.4,.9]])
    w=np.array([.2,.5,.3])
    a,b,gain=choose_pair(u,w,[0,1,2])
    p=sigmoid(12*(u[:,a]-u[:,b]));left=w@p
    after=left*((w*p/left)@u).max()+(1-left)*((w*(1-p)/(1-left))@u).max()
    assert np.isclose(gain,after-(w@u).max())

def test_answer_shifts_preferences_toward_chosen_feature():
    products=[{'id':'a','features':[1,0,0,0,0,0,0]},{'id':'b','features':[0,1,0,0,0,0,0]}]
    u,w=posterior(products,[{'a':'a','b':'b','choice':'a'}])
    mean=w@PARTICLES
    assert mean[0]>mean[1]
    assert np.isclose(w.sum(),1)

def test_skip_does_not_change_posterior():
    p=[{'id':'a','features':[1]*7},{'id':'b','features':[0]*7}]
    _,w=posterior(p,[]);_,skipped=posterior(p,[{'a':'a','b':'b','choice':'skip'}])
    assert np.array_equal(w,skipped)

def test_query_respects_filters_and_does_not_repeat():
    u=np.array([[.1,.5,.8,.9],[.9,.8,.5,.1]])
    assert choose_pair(u,np.array([.5,.5]),[1,2],{(1,2)}) is None
    pair=choose_pair(u,np.array([.5,.5]),[1,2])
    assert set(pair[:2])=={1,2}

def test_information_gain_is_nonnegative():
    rng=np.random.default_rng(2);u=rng.random((100,10));w=np.ones(100)/100
    assert choose_pair(u,w,list(range(10)))[2]>=0
