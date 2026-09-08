# What are AI hallucinations? Why AIs sometimes make things up

*Anna Choi · 20250321 · The Conversation*

Source: [https://theconversation.com/what-are-ai-hallucinations-why-ais-sometimes-make-things-up-242896](https://theconversation.com/what-are-ai-hallucinations-why-ais-sometimes-make-things-up-242896)

When someone sees something that isn’t there, people often refer to the experience as a hallucination. [Hallucinations](https://www.merriam-webster.com/dictionary/hallucination) occur when your sensory perception does not correspond to external stimuli.

Technologies that rely on artificial intelligence can have hallucinations, too.

When an algorithmic system generates information that seems plausible but is actually inaccurate or misleading, computer scientists call it an AI hallucination. Researchers have found these behaviors in different types of AI systems, from chatbots such as [ChatGPT](https://pmc.ncbi.nlm.nih.gov/articles/PMC9939079/) to [image generators](https://aclanthology.org/2023.emnlp-main.20/) such as Dall-E to [autonomous vehicles](https://pratt.duke.edu/news/engineers-develop-hack-to-make-automotive-radar-hallucinate/). We are [information science](https://scholar.google.com/citations?hl=en&user=cGB8_a8AAAAJ&view_op=list_works&sortby=pubdate) [researchers](https://scholar.google.com/citations?hl=en&user=m8Fcl7QQLMAC&view_op=list_works&sortby=pubdate) who have studied hallucinations in AI speech recognition systems.

Wherever AI systems are used in daily life, their hallucinations can pose risks. Some may be minor – when a chatbot gives the wrong answer to a simple question, the user may end up ill-informed. But in other cases, the stakes are much higher. From courtrooms where AI software is used to [make sentencing decisions](https://doi.org/10.1080/0731129X.2023.2275967) to health insurance companies that use algorithms to [determine a patient’s eligibility](https://doi.org/10.1001/jamahealthforum.2024.0622) for coverage, AI hallucinations can have life-altering consequences. They can even be life-threatening: Autonomous vehicles use [AI to detect obstacles](https://doi.org/10.1016/j.jksuci.2022.03.013), other vehicles and pedestrians.

## Making it up

Hallucinations and their effects depend on the type of AI system. With large language models – the underlying technology of AI chatbots – hallucinations are pieces of information that sound convincing but are incorrect, made up or irrelevant. An AI chatbot might create a reference to a scientific article that doesn’t exist or provide a historical fact that is simply wrong, yet [make it sound believable](https://doi.org/10.1145/3571730).

In a 2023 [court case](https://www.reuters.com/legal/new-york-lawyers-sanctioned-using-fake-chatgpt-cases-legal-brief-2023-06-22/), for example, a New York attorney submitted a legal brief that he had written with the help of ChatGPT. A discerning judge later noticed that the brief cited a case that ChatGPT had made up. This could lead to different outcomes in courtrooms if humans were not able to detect the hallucinated piece of information.

#####

With AI tools that can recognize objects in images, hallucinations occur when the AI generates captions that are not faithful to the provided image. Imagine asking a system to list objects in an image that only includes a woman from the chest up talking on a phone and receiving a response that says a woman talking on a phone [while sitting on a bench](https://doi.org/10.18653/v1/D18-1437). This inaccurate information could lead to different consequences in contexts where accuracy is critical.

## What causes hallucinations

Engineers build AI systems by gathering massive amounts of data and feeding it into a computational system that detects patterns in the data. The system develops methods for responding to questions or performing tasks based on those patterns.

Supply an AI system with 1,000 photos of different breeds of dogs, labeled accordingly, and the system will soon learn to detect the difference between a poodle and a golden retriever. But feed it a photo of a blueberry muffin and, as [machine learning researchers](https://www.kaggle.com/datasets/samuelcortinhas/muffin-vs-chihuahua-image-classification) have shown, it may tell you that the muffin is a chihuahua.

[![two side-by-side four-by-four grids of images](https://images.theconversation.com/files/656105/original/file-20250318-56-lc58g2.jpg?ixlib=rb-4.1.1&q=15&auto=format&w=754&h=377&fit=crop&dpr=3)](https://images.theconversation.com/files/656105/original/file-20250318-56-lc58g2.jpg?ixlib=rb-4.1.1&q=45&auto=format&w=1000&fit=clip)


Object recognition AIs can have trouble distinguishing between chihuahuas and blueberry muffins and between sheepdogs and mops.
[Shenkman et al](https://doi.org/10.48550/arXiv.2201.11105), [CC BY](http://creativecommons.org/licenses/by/4.0/)

When a system doesn’t understand the question or the information that it is presented with, it may hallucinate. Hallucinations often occur when the model fills in gaps based on similar contexts from its training data, or when it is built using biased or incomplete training data. This leads to incorrect guesses, as in the case of the mislabeled blueberry muffin.

It’s important to distinguish between AI hallucinations and intentionally creative AI outputs. When an AI system is asked to be creative – like when writing a story or generating artistic images – its novel outputs are expected and desired. Hallucinations, on the other hand, occur when an AI system is asked to provide factual information or perform specific tasks but instead generates incorrect or misleading content while presenting it as accurate.

The key difference lies in the context and purpose: Creativity is appropriate for artistic tasks, while hallucinations are problematic when accuracy and reliability are required.

To address these issues, companies have suggested using high-quality training data and limiting AI responses to follow certain [guidelines](https://www.ibm.com/topics/ai-hallucinations). Nevertheless, these issues may persist in popular AI tools.

Large language models hallucinate in several ways.

## What’s at risk

The impact of an output such as calling a blueberry muffin a chihuahua may seem trivial, but consider the different kinds of technologies that use image recognition systems: An autonomous vehicle that fails to identify objects could lead to a [fatal traffic accident](https://www.npr.org/2019/11/07/777438412/feds-say-self-driving-uber-suv-did-not-recognize-jaywalking-pedestrian-in-fatal-). An autonomous military drone that misidentifies a target could put civilians’ lives in danger.

For AI tools that provide automatic speech recognition, hallucinations are AI transcriptions that include words or phrases that were [never actually spoken](https://doi.org/10.1145/3630106.3658996). This is more likely to occur in noisy environments, where an AI system may end up adding new or irrelevant words in an attempt to decipher background noise such as a passing truck or a crying infant.

As these systems become more regularly integrated into health care, social service and legal settings, hallucinations in automatic speech recognition could lead to inaccurate clinical or legal [outcomes that harm](https://doi.org/10.1145/3630106.3658996) patients, criminal defendants or families in need of social support.

## Check AI’s work

Regardless of AI companies’ efforts to mitigate hallucinations, users should stay vigilant and question AI outputs, especially when they are used in contexts that require precision and accuracy. Double-checking AI-generated information with trusted sources, consulting experts when necessary, and recognizing the limitations of these tools are essential steps for minimizing their risks.
