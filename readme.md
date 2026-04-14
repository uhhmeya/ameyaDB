cd terraform
terraform apply

terraform destroy

# bastion
ssh -A -i ~/.ssh/ameyaDB ec2-user@<bastion_ip>

# ec2
ssh -i ~/.ssh/ameyaDB ec2-user@node-0.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-1.ameyadb.internal
ssh -i ~/.ssh/ameyaDB ec2-user@node-2.ameyadb.internal

# compile & run
cd ameyaDB/engine/src
git pull && g++ -o node *.cpp -lpthread && ./node 0









