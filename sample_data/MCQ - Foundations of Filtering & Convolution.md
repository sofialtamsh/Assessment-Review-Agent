\*\*1. What is a kernel in the context of image filtering?\*\*

A. A full-size copy of the input image used for comparison

B. A function that resizes the image to a fixed dimension

C. A single pixel value used to replace noisy pixels

D. A small matrix of weights that defines how neighboring pixels combine to produce each output pixel

\*\*Answer: D\*\*

A kernel is "a small matrix of weights that defines the rule for how neighboring pixels combine to produce each output pixel." Kernel, filter, and mask all refer to the same thing.

\---

\*\*2. What sizes are typically used for a kernel?\*\*

A. Even-sized matrices such as 2×2 or 4×4

B. Any rectangular matrix such as 3×5 or 2×4

C. Small, odd-sized matrices such as 3×3 or 5×5

D. A single row or column vector

\*\*Answer: C\*\*

"A kernel is usually a small, odd-sized matrix, such as 3×3 or 5×5." Odd sizes ensure there is always a clear center pixel.

\---

\*\*3. What are the four steps of convolution, in the correct order?\*\*

A. Multiply → Place → Sum → Slide

B. Place → Multiply → Sum → Slide

C. Slide → Place → Multiply → Sum

D. Sum → Multiply → Slide → Place

\*\*Answer: B — Place → Multiply → Sum → Slide\*\*

Four steps: (1) Place the kernel at the top-left, (2) Multiply each weight by the pixel beneath it, (3) Sum all products to get one output pixel, (4) Slide to the next position and repeat.

\---

\*\*4. What are the two fundamental categories of filtering?\*\*

A. Compression and Expansion

B. Encoding and Decoding

C. Smoothing and Sharpening

D. Rotation and Translation

\*\*Answer: C — Smoothing and Sharpening\*\*

"There are Two Fundamental Categories of Filtering — Smoothing and Sharpening."

\---

\*\*5. What is the term for the property that the same kernel weights are applied at every position in the image?\*\*

A. Kernel replication

B. Pixel broadcasting

C. Weight sharing

D. Positional encoding

\*\*Answer: C — Weight sharing\*\*

"The kernel does NOT change as it slides — the same weights are applied at every position. This is called weight sharing and is a key property that makes convolution efficient and powerful."

\---

\*\*6. What is the trade-off of applying strong smoothing to an image?\*\*

A. The image becomes too bright and loses contrast

B. Noise is reduced, but edges can become less clear

C. The image resolution increases permanently

D. Sharpening is automatically applied to compensate

\*\*Answer: B\*\*

The smoothing trade-off directly: "Strong smoothing can make edges less clear." Smoothing averages neighboring pixels, which reduces both noise and edge sharpness.

\---

\*\*7. In image filtering, the kernel is often compared to a "program" and convolution to an "executor." What is the most accurate interpretation of this analogy?\*\*

A. Convolution decides what effect to apply; the kernel runs the calculation

B. The kernel's weights entirely determine the output effect; convolution is just the mechanical process of applying those weights across the image

C. Both kernel and convolution must be changed to produce a different result

D. The kernel runs independently of convolution for each pixel

\*\*Answer: B\*\*

"The output depends entirely on the kernel weights. The SAME convolution operation with DIFFERENT kernels produces completely different results. The kernel is the 'program' and convolution is the 'executor'."

\---

\*\*8. Why is raw pixel data described as "not enough for analysis”?\*\*

A. Raw pixels are always stored in BGR format which is incompatible with analysis tools

B. Raw pixels have too many channels to process efficiently

C. Images may contain noise, unimportant background, blur, or hidden structure that makes direct analysis unreliable

D. Raw pixels cannot be converted to NumPy arrays without filtering first

\*\*Answer: C\*\*

Filtering by explaining that raw pixels are often insufficient because images may contain noise, unimportant background, blur, and hidden structure — all of which filtering helps address.

\---

\*\*9. What is a "feature map" in the context of convolution?\*\*

A. A visual legend describing the colors used in the output image

B. The original input image stored in memory

C. The new output image produced by convolution, where each pixel represents a local computation from the original

D. A matrix that stores only the kernel weights used during convolution

\*\*Answer: C\*\*

"Convolution transforms the input image into a new output image (called a feature map), where each pixel represents a local computation from the original."

\---

\*\*10. How does sharpening produce its effect?\*\*

A. It averages nearby pixels to smooth out fine details

B. It replaces all dark pixels with bright ones to increase visibility

C. It emphasizes differences between nearby pixels, increasing contrast around edges so boundaries look more distinct

D. It copies the center pixel value to all surrounding pixels in the kernel region

\*\*Answer: C\*\*

Sharpening \- "Emphasizes differences between nearby pixels. Enhances edges and fine details. Increases contrast around edges, so boundaries look more distinct."

\---

\*\*11. A 3×3 smoothing kernel has all weights equal to 1/9. It is placed over a patch where all 9 pixel values are 90\. What is the output pixel value?\*\*

A. 9

B. 810

C. 90

D. 10

\*\*Answer: C — 90\*\*

Following the convolution steps: multiply each of the 9 pixel values (90) by the corresponding weight (1/9) → 9 products of 10 each → sum \= 9 × 10 \= 90\. Averaging identical values always returns the same value.

\---

\*\*12. A developer needs to reduce grain and sensor noise in a CCTV image before further processing. Which type of kernel should they apply first?\*\*

A. A sharpening kernel, to make the noise pixels stand out for easier removal

B. An edge-detection kernel, to isolate the noisy boundary regions

C. A smoothing kernel, to average neighboring pixels and reduce small pixel-to-pixel variations

D. No kernel — filtering should only be applied after feature extraction

\*\*Answer: C — smoothing kernel\*\*

Smoothing is making "nearby pixels more similar" and "reducing noise and sensor artifacts." It is the correct first step for noise reduction \- this in the real-world filtering pipeline: Noise Reduction (Smoothing) comes before Edge Enhancement.

\---

\*\*13. During convolution, a kernel is placed at a position and produces 9 products. The products are: 2, 4, 6, 1, 3, 5, 7, 8, 9\. What single value is written into the output image at this position?\*\*

A. 9 (the maximum product)

B. 5 (the middle/median product)

C. 45 (the sum of all products)

D. 5 (the average of all products)

\*\*Answer: C — 45\*\*

Step 3 of convolution is "Sum": "Add all 9 products together. This single number becomes one pixel in the output image." 2+4+6+1+3+5+7+8+9 \= 45\.

\---

\*\*14. A self-driving car's vision pipeline must detect lane boundaries. According to the real-world filtering pipeline, which sequence is correct?\*\*

A. Feature Extraction → Noise Reduction → Edge Enhancement → Object Detection

B. Object Detection → Edge Enhancement → Noise Reduction → Feature Extraction

C. Noise Reduction (Smoothing) → Edge Enhancement (Sharpening) → Feature Extraction → Object Detection

D. Edge Enhancement → Noise Reduction → Object Detection → Feature Extraction

\*\*Answer: C\*\*

The filtering pipeline is: Raw Camera Image → Noise Reduction (Smoothing) → Edge Enhancement (Sharpening) → Feature Extraction → Object Detection. This order is intentional — you clean the image before enhancing structure.

\---

\*\*15. There are three key properties that make convolution powerful. Which option correctly identifies all three?\*\*

A. Brightness, Contrast, and Sharpness

B. Parallelism, Memory efficiency, and Speed

C. Local Operations, Reusability (same kernel everywhere), and Efficiency (only 9 weights regardless of image size)

D. Normalization, Scaling, and Translation

\*\*Answer: C\*\*

The exact three properties: (1) Local Operations — each output pixel depends only on a small neighborhood; (2) Reusable — the same kernel scans the whole image; (3) Efficiency — a 3×3 kernel has only 9 weights no matter how large the image is.

\---

\*\*16. What is the key distinction between classical image filtering and CNNs?\*\*

A. CNNs use larger kernels; classical filtering uses only 3×3 kernels

B. CNNs apply smoothing only; classical filtering applies both smoothing and sharpening

C. In classical filtering, kernels are designed by hand; in CNNs, kernels are learned automatically from data

D. Classical filtering uses convolution; CNNs use a completely different mathematical operation

\*\*Answer: C\*\*

"The key difference is in classical image processing, kernels are designed by hand. In CNNs, kernels are learned automatically from data." The underlying convolution mechanism is the same in both.

\---

\*\*17. What characterises the output of an edge-detection kernel specifically, and how does it differ from smoothing or sharpening outputs?\*\*

A. Edge detection blurs the image uniformly; smoothing keeps edges sharp

B. Edge detection and sharpening both produce the same crisp output

C. Edge detection produces an edge map with high values at boundaries and near-zero values in flat regions; smoothing produces a blurred image; sharpening produces a crisp image with amplified pixel differences

D. All three kernel types produce identical outputs, only at different speeds

\*\*Answer: C\*\*

There are three outputs: Smoothing → blurred image, pixels more similar to neighbors; Sharpening → crisp image, pixel differences amplified; Edge-Detection → edge map, high values at boundaries and zero in flat regions.

\---

\*\*18. A radiologist wants to detect tumor boundaries in an MRI scan. The raw scan has significant sensor noise. A colleague suggests applying a sharpening kernel directly. Why is this decision problematic, and what would be the better approach?\*\*

A. Sharpening should never be used in medical imaging under any circumstance

B. Sharpening amplifies differences between pixels — applying it to a noisy image would also amplify the noise, making boundaries harder to detect. The correct approach is to smooth first to reduce noise, then sharpen to enhance edges

C. Sharpening is correct here; smoothing should never be applied before edge detection

D. The order of filters has no effect on the final output

\*\*Answer: B\*\*

The sharpening emphasizes differences between nearby pixels. Applied to a noisy image, this amplifies noise alongside edges. According to the pipeline, Noise Reduction (Smoothing) must come before Edge Enhancement (Sharpening) — this is exactly why order matters in the filtering pipeline.

\---

\*\*19. A computer vision engineer is choosing between a 3×3 kernel and a 5×5 kernel for noise reduction. Which statement best evaluates this trade-off?\*\*

A. A 5×5 kernel is always wrong — kernels must be 3×3 only

B. A 3×3 kernel is more efficient and produces identical output to any larger kernel

C. A 5×5 kernel considers a larger neighborhood so may smooth more aggressively — which can reduce noise more but also risks making edges less clear; the trade-off between noise reduction and edge preservation must guide the choice

D. Kernel size has no effect on the output — only the weight values matter

\*\*Answer: C\*\*

The kernels look at "a local group of pixels" and that strong smoothing can make edges less clear. A larger kernel covers a wider neighborhood, smoothing more aggressively — beneficial for noise but harmful to fine edge detail.

\---

\*\*20. An engineer builds a pipeline to detect vehicle license plates from CCTV footage. The raw frames are noisy (low-light grain) and the plates appear slightly blurry. The engineer applies a single sharpening kernel to all frames and then feeds the output directly into a license plate detector. The detector performs poorly.

Analyze and identify the most complete explanation for its failure, and what the corrected pipeline should look like.\*\*

A. The problem is the detector model — filtering has no effect on detection accuracy

B. Sharpening was applied correctly; the issue is that the kernel was too small (should use 5×5 instead of 3×3)

C. Applying sharpening to a noisy image amplifies the noise along with the edges, making it harder for the detector to find plates. The corrected pipeline should be: Smoothing first (to reduce grain) → Sharpening (to enhance plate characters) → Feature Extraction → Detection

D. Filtering should not be used before object detection; raw frames should always be fed directly into detectors

\*\*Answer: C\*\*

Two errors compound here: (1) Sharpening amplifies differences — on a noisy frame, this amplifies grain as much as edges, producing a noisier, harder-to-read result. (2) The real-world pipeline explicitly puts Noise Reduction (Smoothing) before Edge Enhancement (Sharpening), which then feeds Feature Extraction and Object Detection. Skipping smoothing and going straight to sharpening violates this sequence, degrading downstream detection performance.  
