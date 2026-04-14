#!/bin/bash

KEY="~/.ssh/ameyaDB"

# apply infrastructure
cd terraform
terraform apply -auto-approve

# get bastion ip
BASTION=$(terraform output -raw bastion_ip)
cd ..

# start all nodes
for i in 0 1 2; do
    ssh -A -i $KEY -o StrictHostKeyChecking=no \
        -J ec2-user@$BASTION ec2-user@node-${i}.ameyadb.internal \
        "[ -d ameyaDB ] || git clone https://github.com/uhhmeya/ameyaDB ameyaDB && cd ameyaDB/engine/src && git pull && g++ -o node main.cpp -I/usr/local/include -L/usr/local/lib64 -laws-cpp-sdk-sns -laws-cpp-sdk-sqs -laws-cpp-sdk-core -laws-crt-cpp -laws-c-auth -laws-c-http -laws-c-io -laws-c-common -lpthread -Wl,-rpath,/usr/local/lib64 && ./node ${i}" &
done

wait

