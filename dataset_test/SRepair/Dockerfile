FROM ubuntu:20.04

# 1. 更新并安装基础依赖
RUN apt-get update -y && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    vim git zsh wget curl file htop screen \
    openjdk-8-jdk software-properties-common \
    ant python3 python3-pip build-essential \
    subversion perl unzip cpanminus make && \
    apt-get clean

# 2. 设置 Java 环境变量
ENV JAVA_HOME /usr/lib/jvm/java-8-openjdk-amd64/

# 3. 克隆 defects4j 仓库（单独步骤，便于重试）
RUN git clone https://github.com/rjust/defects4j.git defects4j

# 4. 安装 Perl 依赖
RUN cd /defects4j && cpanm --installdeps .

#5. 初始化 defects4j
RUN cd /defects4j && ./init.sh

# 6. 添加 defects4j 到 PATH
ENV PATH="/defects4j/framework/bin:${PATH}"

# 7. 安装 Python 依赖
RUN pip install psutil tqdm tiktoken openai && \
    pip install git+https://github.com/huggingface/transformers.git@main

# 8. 复制本地代码
ADD ./ /data/LLM4APR

# 9. 设置默认启动命令
ENTRYPOINT ["/bin/bash"]