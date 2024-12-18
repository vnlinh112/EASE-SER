import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import savgol_filter
import umap
import torch 
from torch import nn, Tensor
from torch.nn import functional as F
from functools import partial
from einops import rearrange, repeat, reduce
from typing import Optional, Literal, Iterable, Union

import librosa
from librosa import display
import matplotlib.pyplot as plt
import seaborn as sns
import umap
sns.set_theme(style="dark")

from .zero_crossing import zero_crossings, zero_crossing_score_chunks_v3, zero_crossing_score_chunks_v2
from .audio import AudioLibrosa

from matplotlib import ticker
sr = 16000

def visualize_speech_codebook(
        waves: Iterable, 
        colors: Optional[Iterable]=None, 
        title="", 
        expand=False, 
        n=16,
        feature_mel=True,
        feature_player=False,
        default_color: Optional[str]=None,
        figsize_unit=(6,5),
        ncols=8,
        return_plot=False,
        waveplot_librosa=True,
        y_formatter=None):
    players = []
    if expand:
        ncols = 4
        fig, ax = plt.subplots(
            ncols=ncols, nrows=n//ncols, 
            figsize=(8*ncols, 5*n//ncols))
    else:
        fig, ax = plt.subplots(
            ncols=ncols, nrows=n//ncols, 
            figsize=(figsize_unit[0]*ncols, figsize_unit[1]*n//ncols))
    axi = ax.ravel()    
    i = 0
    
    if feature_mel:
        num_codes = n//2
        win_length = 256
    else:
        num_codes = n
        win_length = 512
    for x, y in enumerate(waves[:num_codes]):
        
        audio = AudioLibrosa(
            y=y, sr=sr, title=f"{title}{x}",
            win_length=win_length,
            hop_length=win_length//2,
            n_mels=64, n_mfcc=13,
            features_f0=feature_mel,
            features_fft=feature_mel,
            features_player=feature_player, 
            features_cqt=False,
            center=False)
        audio.extract_features()
        if feature_player:
            players.append(audio.player)

        if colors is None or len(colors) < 0:
            color = default_color
        else:
            color = colors[x]
        
        if color is None:
            c1 = np.max(audio.voiced_probs)*0.5 + 0.5
            c2 = max(1, min(0.5, 1 - np.max(audio.f0) / 3000))
            color = (0.5,c2*c1,c1)
        
        if waveplot_librosa:
            img = display.waveshow(
                audio.y, sr=sr, ax=axi[i], color=color)
        else:
            times = audio.samples_to_time(audio.y)
            axi[i].plot(audio.y, color=color)
            if y_formatter:
                axi[i].yaxis.set_major_formatter(
                    ticker.StrMethodFormatter(y_formatter))
        axi[i].set(title=audio.title)
        axi[i].set(xlabel=None)
        axi[i].xaxis.set_major_formatter(
            ticker.StrMethodFormatter("{x:.2f}"))
        i += 1

        if feature_mel:
            audio.show_spectrogram(
                audio.melspectrogram, 
                convert_db='power', y_axis='mel', 
                ax=axi[i], fig=fig, 
                title='Melspectrogram & F0', 
                colorbar=expand)  
            audio.show_f0(ax=axi[i])
            axi[i].set(xlabel=None)
            axi[i].xaxis.set_major_formatter(
                ticker.StrMethodFormatter("{x:.2f}"))
            
            i += 1
    axi[i-1].set(xlabel="Time")
    if feature_player:
        return players
    if return_plot:
        return (fig, ax)


def get_embedding_color(    
    y: Tensor,
    n_fft: int = 1024,
    stride: int = 256
) -> Tensor:
    """Compute the zero-crossing score of the codebook embedding.

    Returns
    -------
    zcr : np.ndarray [shape=(..., 1, t)]
        ``zcr[..., 0, i]`` is the zero crossing score in frame ``i`` 
        with score in range [0,1]
    """
    crossings = zero_crossings(y, dtype=torch.float)
    zcrate = crossings.mean(dim=-1)
    nonzero_mean = torch.where(
        crossings>0, crossings, 0.0).mean(dim=-1)
    score = F.sigmoid(1 - 8*zcrate + 2*nonzero_mean)
    color = torch.stack(
        [torch.full_like(score, 0.5), score, score], 
        dim=-1).numpy()
    return color, score

def get_embedding_color_v2(
        y: Tensor, mask_ratio=0.2, 
        score_offset=0.5,
        voice_noise_color: Literal[
            'blue_orange', 'blue_gray', 
            'green_pink', 'cyan_gray']='cyan_gray',
        alpha: float = 0.75
    ) -> tuple[np.ndarray, Tensor]:
    score = zero_crossing_score_chunks_v2(
        y, mask_ratio=mask_ratio, score_offset=score_offset)
    color = get_zcs_color_v2(
        score, voice_noise_color=voice_noise_color, alpha=alpha)
    return color, score

def get_zcs_color(zcs: Tensor):
    score_sig = F.sigmoid(zcs)
    color = torch.stack(
        [1-score_sig, torch.full_like(zcs, 0.5), score_sig], 
        dim=-1).numpy()
    return color

def get_zcs_color_v2(
        zcs: Tensor, 
        voice_noise_color: Literal[
            'blue_orange', 'blue_gray', 
            'green_pink', 'cyan_gray']='cyan_gray',
        alpha: float = 0.75):
    alpha = min(max(alpha, 0), 1)
    if voice_noise_color == 'blue_orange':
        score_sig = torch.clamp(
            F.softplus(zcs, beta=40.0, threshold=0.5)*10, max=1)*alpha
        color = torch.stack(
            [1-score_sig, torch.full_like(zcs, 0.5), score_sig], 
            dim=-1).numpy()
    elif voice_noise_color == 'blue_gray':
        score_sig = torch.sigmoid(
            F.softplus(zcs, beta=40.0, threshold=0.5)*10)*alpha
        color = torch.stack(
            [1-score_sig, torch.full_like(zcs, 0.5), score_sig], 
            dim=-1).numpy()
    elif voice_noise_color == 'green_pink':
        score_sig = torch.clamp(
            F.softplus(zcs, beta=40.0, threshold=0.5)*10, max=1)*alpha
        color = torch.stack(
            [1-score_sig, score_sig, torch.full_like(zcs, 0.5)], 
            dim=-1).numpy()
    else: # cyan_gray
        score_sig = torch.sigmoid(
            F.softplus(zcs, beta=40.0, threshold=0.5)*10)*alpha
        color = torch.stack(
            [1-score_sig, score_sig, score_sig], 
            dim=-1).numpy()
    return color


def visualize_embedding_umap(
        data, colors, edgecolors="black",
        n_neighbors=15, min_dist=0.1, 
        n_components=2, metric='euclidean', title=''
    ):
    transformer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=n_components,
        metric=metric)
    u = transformer.fit_transform(data)
    fig = plt.figure()
    if n_components == 1:
        ax = fig.add_subplot(111)
        ax.scatter(
            u[:,0], range(len(u)), 
            c=colors, edgecolors= edgecolors)
    if n_components == 2:
        ax = fig.add_subplot(111)
        ax.scatter(
            u[:,0], u[:,1], 
            c=colors, edgecolors=edgecolors)
    if n_components == 3:
        ax = fig.add_subplot(111, projection='3d')
        ax.scatter(
            u[:,0], u[:,1], u[:,2], 
            s=100, c=colors, edgecolors=edgecolors)
    plt.title(title, fontsize=18)


def transform_and_visualize_umap(
        transformer, data, target, classnames, 
        edgecolors=None, title=''
    ):
    u = transformer.transform(data)
    fig, ax = plt.subplots(1, figsize=(8, 4))
    plt.scatter(u[:,0], u[:,1], c=target, cmap='Spectral', 
                edgecolors=edgecolors)
    plt.setp(ax, xticks=[], yticks=[])
    num_classes = len(classnames)
    cbar = plt.colorbar(boundaries=np.arange(num_classes+1)-0.5)
    cbar.set_ticks(np.arange(num_classes))
    cbar.set_ticklabels(classnames)
    plt.title(title)
    return u
    
def train_and_visualize_embedding_umap(
        data, target, classnames, 
        masked_target=None, mask_ratio=None,
        n_epochs=500, learning_rate=0.001,
        edgecolors="black",
        n_neighbors=15, min_dist=0.1, 
        n_components=2, metric='euclidean', output_metric='euclidean', 
        title=''
    ):
    if masked_target is None:
        masked_target = target.clone()
        if mask_ratio is not None:
            masked_target[np.random.choice(
                len(target), size=int(len(target)*mask_ratio), replace=False)] = -1
    transformer = umap.UMAP(
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        n_components=n_components,
        n_epochs=n_epochs, 
        learning_rate=learning_rate,
        metric=metric, output_metric=output_metric)
    transformer = transformer.fit(data, y=masked_target)
    u = transform_and_visualize_umap(
        transformer, data, target, classnames, 
        edgecolors=edgecolors, title=title)
    return transformer, u


def visualize_training_curves(
        test_accuracy, train_cls_loss,
        train_recon_loss, train_perplexity,
        train_smooth_params = (301, 7),
        test_smooth_params = (3, 2)
):
    train_smooth_fn = partial(
        savgol_filter, 
        window_length=train_smooth_params[0], 
        polyorder=train_smooth_params[1])
    test_smooth_fn = partial(
        savgol_filter, 
        window_length=test_smooth_params[0], 
        polyorder=test_smooth_params[1])
    try:
        test_accuracy = test_smooth_fn(test_accuracy)
        train_cls_loss = train_smooth_fn(train_cls_loss)
        train_recon_loss = train_smooth_fn(train_recon_loss)
        train_perplexity = train_smooth_fn(train_perplexity)
    except Exception:
        pass
    
    f = plt.figure(figsize=(12,3))
    ax = f.add_subplot(1,4,1)
    ax.plot(test_accuracy)
    ax.set_title('Test accuracy')
    ax.set_xlabel('iteration')

    ax = f.add_subplot(1,4,2)
    ax.plot(train_cls_loss)
    ax.set_title('Train cls loss')
    ax.set_xlabel('iteration')

    ax = f.add_subplot(1,4,3)
    ax.plot(train_recon_loss)
    ax.set_title('SNR-based loss')
    ax.set_xlabel('iteration')

    ax = f.add_subplot(1,4,4)
    ax.plot(train_perplexity)
    ax.set_title('Avg. codebook usage')
    ax.set_xlabel('iteration')


