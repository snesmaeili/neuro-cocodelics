from typing import Callable, List, Optional, Tuple

import mne
import numpy as np
from joblib import Parallel, delayed
from tqdm import trange


def sliding_window(
    raw: mne.io.Raw,
    func: Callable,
    *,
    window_seconds: Optional[float] = None,
    window_size: Optional[int] = None,
    step_seconds: Optional[float] = None,
    step_size: Optional[int] = None,
    include_chans: List[str] = [],
    exclude_chans: List[str] = [],
    n_jobs: int = -1,
    verbose: bool = True,
) -> Tuple[np.ndarray, List]:
    """
    Apply a function to chunks of data in a sliding window manner. The provided function should follow the signature
    `func(data: np.ndarray, sfreq: float) -> Any` where `data` is a 2D numpy array of shape (n_channels, n_samples).
    The function will be applied to each chunk of data, and the results will be returned along with the corresponding
    window onset times.

    Args:
        raw (mne.io.Raw): MNE Raw object containing EEG data.
        func (Callable): Function to apply to each chunk of data.
        window_seconds (Optional[float]): Size of the sliding window in seconds.
        window_size (Optional[int]): Size of the sliding window in samples. Mutually exclusive with `window_seconds`.
        step_seconds (Optional[float]): Step size for the sliding window in seconds.
        step_size (Optional[int]): Step size for the sliding window in samples. Mutually exclusive with `step_seconds`.
        include_chans (List[str]): List of channel names to include.
        exclude_chans (List[str]): List of channel names to exclude.
        n_jobs (int): Number of parallel jobs to run. -1 means using all processors.
        verbose (bool): Whether to print progress messages.
    Returns:
        Tuple[np.ndarray, List]: Window onset times and results returned by the function.
    """
    raw = raw.copy()
    sfreq = raw.info["sfreq"]

    if window_seconds is not None and window_size is not None:
        raise ValueError("Arguments `window_seconds` and `window_size` are mutually exclusive. Please provide only one.")
    elif window_seconds is not None:
        window_size = int(window_seconds * sfreq)
    elif window_size is None:
        raise ValueError("Either `window_seconds` or `window_size` must be provided.")

    if step_seconds is not None and step_size is not None:
        raise ValueError("Arguments `step_seconds` and `step_size` are mutually exclusive. Please provide only one.")
    elif step_seconds is not None:
        step_size = int(step_seconds * sfreq)
    elif step_size is None:
        step_size = window_size

    # Select channels to include or exclude
    if include_chans:
        raw.pick_channels(include_chans)
    elif exclude_chans:
        raw.drop_channels(exclude_chans)

    # apply the function to chunks of data
    data = raw.get_data()
    times = np.arange(0, len(data[0]) - window_size, step_size) / sfreq
    results = Parallel(n_jobs=n_jobs)(
        delayed(func)(data[:, i : i + window_size], sfreq)
        for i in trange(0, data.shape[1] - window_size, step_size, disable=not verbose)
    )

    # remove None results and corresponding times
    missing = [i for i in range(len(results)) if results[i] is None]
    times = np.delete(times, missing)
    results = [res for i, res in enumerate(results) if i not in missing]
    return times, results


def batched_sliding_window(
    raw: mne.io.Raw,
    func: Callable,
    *,
    window_seconds: Optional[float] = None,
    window_size: Optional[int] = None,
    step_seconds: Optional[float] = None,
    step_size: Optional[int] = None,
    include_chans: List[str] = [],
    exclude_chans: List[str] = [],
    batch_size: int = 100,
    n_jobs: int = 1,
    verbose: bool = True,
) -> Tuple[np.ndarray, List]:
    """
    Apply a function to chunks of data in a sliding window manner, processing the data in batches. The provided function
    should follow the signature `func(data: np.ndarray, sfreq: float) -> Any` where `data` is a 3D numpy array of shape
    (n_batches, n_channels, n_samples). The function will be applied to each chunk of data, and the results will be
    returned along with the corresponding window onset times.

    Args:
        raw (mne.io.Raw): MNE Raw object containing EEG data.
        func (Callable): Function to apply to each chunk of data.
        window_seconds (Optional[float]): Size of the sliding window in seconds.
        window_size (Optional[int]): Size of the sliding window in samples. Mutually exclusive with `window_seconds`.
        step_seconds (Optional[float]): Step size for the sliding window in seconds.
        step_size (Optional[int]): Step size for the sliding window in samples. Mutually exclusive with `step_seconds`.
        include_chans (List[str]): List of channel names to include.
        exclude_chans (List[str]): List of channel names to exclude.
        batch_size (int): Number of chunks to process in each batch.
        n_jobs (int): Number of parallel jobs to run. -1 means using all processors.
        verbose (bool): Whether to print progress messages.
    Returns:
        Tuple[np.ndarray, List]: Window onset times and results returned by the function.
    """
    raw = raw.copy()
    sfreq = raw.info["sfreq"]
    times, windows = sliding_window(
        raw,
        lambda x, _: x,
        window_seconds=window_seconds,
        window_size=window_size,
        step_seconds=step_seconds,
        step_size=step_size,
        include_chans=include_chans,
        exclude_chans=exclude_chans,
        n_jobs=1,
        verbose=False,
    )

    if len(windows) == 0:
        return np.array([]), []
    windows = np.stack(windows, axis=0)
    results = Parallel(n_jobs=n_jobs)(
        delayed(func)(windows[i : i + batch_size], sfreq) for i in trange(0, len(windows), batch_size, disable=not verbose)
    )
    # ensure all results still have the batch size and expand None results
    for i in range(len(results)):
        bs = len(windows[i * batch_size : (i + 1) * batch_size])
        if results[i] is None:
            results[i] = [None] * bs
        elif len(results[i]) != bs:
            raise ValueError(
                f"Function returned {len(results[i])} results for batch {i}, expected {bs}. "
                "Ensure the function returns a list of results with the same length as the batch size."
            )
        else:
            results[i] = list(results[i])
    # flatten the results and remove None results
    results = [item for sublist in results for item in sublist]
    missing = [i for i in range(len(results)) if results[i] is None]
    times = np.delete(times, missing)
    results = [res for i, res in enumerate(results) if i not in missing]
    return times, results
