
from diagnostics import diagnostics
import numpy as np


def numerical_solve_bisect(e2, eps2, k):
    """
    Solve the estimator equation using bisection.
    See Vejmelka et al, IAWF, 2013 for details.
    """
    N = e2.shape[0]
    tgt = N - k
    s2_eta_left = 0.0
    s2_eta_right = 0.01

    # if target is zero, we have the same number of regressors as observations
    # thus our solution will fit perfectly and our estimated error variance
    # will be zero
    if tgt == 0:
        return 0.0

    val_left = np.sum(e2 / eps2)
    val_right = np.sum(e2 / (eps2 + s2_eta_right))

#    print('BISECT: e2 %s eps2 %s N %d k %d val_let %g val_right %g' % (str(e2), str(eps2), N, k, val_left, val_right))

    # if with the minimum possible s2_eta (which is 0), we are below target
    # then a solution does not exist
    if val_left < tgt:
        return 0.0

    while val_right > tgt:
      s2_eta_left = s2_eta_right
      val_left = np.sum(e2 / (eps2 + s2_eta_left))
      s2_eta_right *= 2.0
      val_right = np.sum(e2 / (eps2 + s2_eta_right))

#    print('BISECT: s2_eta_left %g val_left %g s2_eta_right %g val_right %g tgt %g' %
#           (s2_eta_left, val_left, s2_eta_right, val_right, tgt)) 

    while val_left - val_right > 1e-6:
        s2_eta_new = 0.5 * (s2_eta_left + s2_eta_right)
        val = np.sum(e2 / (eps2 + s2_eta_new))

        if val > tgt:
            val_left, s2_eta_left = val, s2_eta_new
        else:
            val_right, s2_eta_right = val, s2_eta_new

    return 0.5 * (s2_eta_left + s2_eta_right)



def trend_surface_model_kriging(obs_data, X):
    """
    Trend surface model kriging, which assumes spatially uncorrelated errors.
    The kriging results in the matrix K, which contains the kriged observations
    and the matrix V, which contains the kriging variance.
    """
    Nobs = len(obs_data)

    # we ensure we have at most Nobs covariates
    Nallcov = min(X.shape[2], Nobs)

    # the matrix of covariates
    Xobs = np.zeros((Nobs, Nallcov))

    # outputs
    K = np.zeros(X[:,:,0].shape)
    V = np.zeros_like(K)

    # the vector of target observations
    y = np.zeros((Nobs,1))

    # the vector of observation variances
    obs_var = np.zeros((Nobs,))

    # fill out matrix/vector structures
    for (obs,i) in zip(obs_data, range(Nobs)):
        p = obs.get_nearest_grid_point()
        y[i,0] = obs.get_value()
        Xobs[i,:] = X[p[0], p[1], :Nallcov]
        obs_var[i] = obs.get_measurement_variance()

    # remove covariates that contain only zeros
    norms = np.sum(Xobs**2, axis = 0) ** 0.5
    nz_covs = np.nonzero(norms)[0]
    Ncov = len(nz_covs)
    X = X[:,:,nz_covs]
    Xobs = Xobs[:,nz_covs]
    norms = norms[nz_covs]

    # normalize all covariates
    for i in range(1, Ncov):
        scalar = norms[0] / norms[i]
        Xobs[:,i] *= scalar
        X[:,:,i] *= scalar

    Xobs = np.asmatrix(Xobs)

    # initialize the iterative algorithm
    s2_eta_hat_old = 10.0
    s2_eta_hat = 0.0
    iters = 0
    subzeros = 0

    # while the relative change
    while abs( (s2_eta_hat_old - s2_eta_hat) / max(s2_eta_hat_old, 1e-8)) > 1e-3:
        #print('TSM: iter %d s_eta_hat_old %g s2_eta_hat %g' % (iters, s2_eta_hat_old, s2_eta_hat))
        s2_eta_hat_old = s2_eta_hat

        # recompute covariance matrix
        Sigma_diag = obs_var + s2_eta_hat
        Sigma = np.diag(Sigma_diag)
        Sigma_1 = np.diag(1.0 / Sigma_diag)
        XtSX = Xobs.T * Sigma_1 * Xobs
        #print('TSM: XtSX = %s' % str(XtSX))

        # QR solution method of the least squares problem
        Sigma_1_2 = np.asmatrix(np.diag(Sigma_diag ** -0.5))
        yt = Sigma_1_2 * y
        Q, R = np.linalg.qr(Sigma_1_2 * Xobs)
        beta = np.linalg.solve(R, np.asmatrix(Q).T * yt)
        res2 = np.asarray(y - Xobs * beta)[:,0]**2
#        print('TSM: beta %s res2 %s' % (str(beta), str(res2)))

        # compute new estimate of variance of microscale variability
        s2_array = res2 - obs_var
        for i in range(len(s2_array)):
            s2_array[i] += np.dot(Xobs[i,:], np.linalg.solve(XtSX, Xobs[i,:].T))

#        print('TSM: s2_array %s' % str(s2_array))
        s2_eta_hat = numerical_solve_bisect(res2, obs_var, Ncov)
        if s2_eta_hat < 0.0:
#          print("TSM: s2_eta_hat estimate below zero")
          s2_eta_hat = 0.0

#        print('TSM: s2_eta_hat %g' % s2_eta_hat)

        subzeros = np.count_nonzero(s2_array < 0.0)
        iters += 1

    # map computed betas to original (possibly extended) betas which include zero variables
    beta_ext = np.asmatrix(np.zeros((Nallcov,1)))
    beta_ext[nz_covs] = beta
    diagnostics().push("s2_eta_hat", s2_eta_hat)
    diagnostics().push("kriging_beta", beta_ext)
    diagnostics().push("kriging_iters", iters)
    diagnostics().push("kriging_rmse", np.mean(res2)**0.5)
    diagnostics().push("kriging_subzero_s2_estimates", subzeros)
    diagnostics().push("kriging_cov_cond", np.linalg.cond(XtSX))

    for i in range(X.shape[0]):
        for j in range(X.shape[1]):
            x_ij = X[i,j,:]
            K[i,j] = np.dot(x_ij, beta)
            V[i,j] = s2_eta_hat + np.dot(x_ij, np.linalg.solve(XtSX, x_ij))
            if V[i,j] < 0.0:
              print("ERROR: negative kriging variance!")

    return K, V

